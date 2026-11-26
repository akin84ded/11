#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1])
gradle = root / "build.gradle"
main = root / "src/main"
java = main / "java/ru/mos2/app/MainActivity.java"
manifest = main / "AndroidManifest.xml"
strings = main / "res/values/strings.xml"

java.parent.mkdir(parents=True, exist_ok=True)
java.write_text(r'''package ru.mos2.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.content.SharedPreferences;
import android.content.Intent;
import android.graphics.Typeface;
import android.view.Gravity;
import android.view.View;
import android.widget.*;
import android.text.TextWatcher;
import android.text.Editable;
import android.Manifest;
import android.content.pm.PackageManager;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.work.Constraints;
import androidx.work.NetworkType;
import androidx.work.PeriodicWorkRequest;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.WorkManager;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private SharedPreferences prefs;
    private LinearLayout list, root, analytics, watchList, portfolioList;
    private final ArrayList<Candidate> candidates = new ArrayList<>();
    private final ArrayList<Holding> holdings = new ArrayList<>();
    private AutoCompleteTextView search;
    private ArrayAdapter<String> searchAdapter;
    private TextView status;
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final ArrayList<Stock> stocks = new ArrayList<>();
    private static final String CACHE = "quotes_cache";
    private static final int REQUEST_EXPORT_BACKUP = 8101;
    private static final int REQUEST_IMPORT_BACKUP = 8102;
    private static class Stock {
        String ticker, name, price, change;
        double changePct;
        Stock(String t, String n, String p, String c, double pct) { ticker=t; name=n; price=p; change=c; changePct=pct; }
    }
    private static class Candidate {
        String ticker, period, recommendation; double entry, stop, target; int score;
        Candidate(String t,double e,double s,double g){this(t,e,s,g,"Среднесрочный");}
        Candidate(String t,double e,double s,double g,String p){ticker=t;entry=e;stop=s;target=g;period=p;recommendation="Не оценено";score=0;}
    }
    private static class Holding {
        String ticker; double quantity,buy,stop,target;
        Holding(String t,double q,double b,double s,double g){ticker=t;quantity=q;buy=b;stop=s;target=g;}
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("prosperity", MODE_PRIVATE);
        loadPlans();
        buildScreen();
        requestNotificationPermission();
        schedulePriceMonitor();
        showCached();
        renderPlans();
        refreshQuotes();
    }

    private void requestNotificationPermission() {
        if (android.os.Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, new String[]{Manifest.permission.POST_NOTIFICATIONS}, 701);
        }
    }
    private void schedulePriceMonitor() {
        Constraints constraints = new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build();
        PeriodicWorkRequest request = new PeriodicWorkRequest.Builder(PriceMonitorWorker.class, 15, java.util.concurrent.TimeUnit.MINUTES).setConstraints(constraints).build();
        WorkManager.getInstance(this).enqueueUniquePeriodicWork("prosperity-price-monitor", ExistingPeriodicWorkPolicy.KEEP, request);
    }

    private int dp(float n) { return (int)(n * getResources().getDisplayMetrics().density + .5f); }
    private TextView text(String s, int size, boolean bold) {
        TextView v = new TextView(this); v.setText(s); v.setTextSize(size);
        v.setTextColor(0xff20252b); v.setPadding(dp(2),dp(5),dp(2),dp(5));
        if (bold) v.setTypeface(null, Typeface.BOLD);
        return v;
    }
    private void buildScreen() {
        ScrollView scroll = new ScrollView(this);
        root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(16),dp(14),dp(16),dp(20)); root.setBackgroundColor(0xfff5f7fa);
        scroll.addView(root); setContentView(scroll);
        root.addView(text("Процветание", 28, true));
        LinearLayout backupBar = new LinearLayout(this); backupBar.setOrientation(LinearLayout.HORIZONTAL);
        Button exportBackup = new Button(this); exportBackup.setText("Экспорт данных");
        Button importBackup = new Button(this); importBackup.setText("Импорт данных");
        backupBar.addView(exportBackup, new LinearLayout.LayoutParams(0, -2, 1));
        backupBar.addView(importBackup, new LinearLayout.LayoutParams(0, -2, 1));
        root.addView(backupBar);
        root.addView(text("Резервная копия включает портфель, кандидатов, заметки и локальный кэш котировок. Храните файл в безопасном месте.", 12, false));
        exportBackup.setOnClickListener(v -> chooseBackupExport());
        importBackup.setOnClickListener(v -> chooseBackupImport());
        root.addView(text("Акции • котировки MOEX • заметки без сервера", 14, false));
        LinearLayout bar = new LinearLayout(this); bar.setOrientation(LinearLayout.HORIZONTAL);
        search = new AutoCompleteTextView(this); search.setSingleLine(true); search.setThreshold(1); search.setCompletionHint("Выберите инструмент по тикеру или названию"); search.setHint("Начните вводить тикер или название, например Сбербанк");
        search.setOnItemClickListener((parent,view,position,id) -> { String choice=(String)parent.getItemAtPosition(position); int sep=choice.indexOf(" — "); String ticker=sep>0?choice.substring(0,sep):choice; search.setText(ticker); search.setSelection(ticker.length()); render(ticker); });
        bar.addView(search, new LinearLayout.LayoutParams(0,dp(52),1));
        Button find = new Button(this); find.setText("Найти"); bar.addView(find);
        root.addView(bar);
        Button update = new Button(this); update.setText("Обновить котировки из интернета");
        root.addView(update);
        status = text("Котировки загружаются…", 13, false); root.addView(status);
        root.addView(text("Аналитика рынка", 21, true));
        analytics = new LinearLayout(this); analytics.setOrientation(LinearLayout.VERTICAL);
        root.addView(analytics);
        root.addView(text("Кандидаты — план входа", 20, true));
        root.addView(text("Добавляйте интересующие тикеры вручную и задавайте цену входа, стоп и цель.",12,false));
        Button addCandidate = new Button(this); addCandidate.setText("Добавить кандидата");
        root.addView(addCandidate); watchList = new LinearLayout(this); watchList.setOrientation(LinearLayout.VERTICAL); root.addView(watchList);
        addCandidate.setOnClickListener(v -> candidateDialog(null));
        root.addView(text("Мои акции — портфель", 20, true));
        root.addView(text("Здесь учитываются только ваши реальные позиции: количество и цена покупки.",12,false));
        Button addHolding = new Button(this); addHolding.setText("Добавить акцию в портфель");
        root.addView(addHolding); portfolioList = new LinearLayout(this); portfolioList.setOrientation(LinearLayout.VERTICAL); root.addView(portfolioList);
        addHolding.setOnClickListener(v -> holdingDialog(null));
        root.addView(text("Котировки и заметки", 20, true));
        list = new LinearLayout(this); list.setOrientation(LinearLayout.VERTICAL); root.addView(list);
        find.setOnClickListener(v -> render(search.getText().toString()));
        search.setOnEditorActionListener((v,a,e) -> { render(search.getText().toString()); return true; });
        update.setOnClickListener(v -> refreshQuotes());
    }

    private void showCached() {
        String raw = prefs.getString(CACHE, "");
        if (!raw.isEmpty()) {
            try { parseQuotes(new JSONObject(raw)); render(""); status.setText("Показаны сохранённые котировки. Проверяю обновления…"); }
            catch (Exception cacheError) { status.setText("Кэш котировок повреждён или имеет неизвестный формат. Попробуйте обновить данные. ("+cacheError.getMessage()+")"); }
        } else status.setText("Для первой загрузки котировок нужен интернет. Затем данные будут доступны офлайн.");
    }

    private void refreshQuotes() {
        status.setText("Получаю актуальные котировки MOEX…");
        io.execute(() -> {
            HttpURLConnection c = null;
            try {
                String endpoint = "/iss/engines/stock/markets/shares/securities.json?iss.meta=off&iss.only=securities,marketdata&securities.columns=SECID,SHORTNAME&marketdata.columns=SECID,LAST,CHANGE&limit=1000";
                JSONObject data = null;
                Exception lastError = null;
                // Все запросы к MOEX выполняются только по HTTPS.
                // 
                for (String scheme : new String[]{"https"}) {
                    try {
                        URL url = new URL(scheme + "://iss.moex.com" + endpoint);
                        c = (HttpURLConnection)url.openConnection();
                        c.setConnectTimeout(12000); c.setReadTimeout(18000);
                        c.setInstanceFollowRedirects(false);
                        c.setRequestProperty("User-Agent","Prosperity-Android/1.0");
                        c.setRequestProperty("Accept","application/json");
                        int code = c.getResponseCode();
                        if (code != 200) throw new IOException(scheme.toUpperCase(Locale.ROOT)+" HTTP "+code);
                        ByteArrayOutputStream out = new ByteArrayOutputStream();
                        try(InputStream in=c.getInputStream()) { byte[] b=new byte[8192]; int n; while((n=in.read(b))!=-1) out.write(b,0,n); }
                        data = new JSONObject(new String(out.toByteArray(), StandardCharsets.UTF_8));
                        break;
                    } catch(Exception attempt) {
                        lastError = attempt;
                    } finally {
                        if(c!=null) { c.disconnect(); c=null; }
                    }
                }
                if (data == null) throw new IOException("HTTPS MOEX недоступен: "+(lastError==null?"неизвестная ошибка":lastError.getMessage()));
                final JSONObject result = data;
                prefs.edit().putString(CACHE,result.toString()).putLong("updated",System.currentTimeMillis()).apply();
                runOnUiThread(() -> { try { parseQuotes(result); render(search.getText().toString()); status.setText("Котировки MOEX обновлены: "+stocks.size()+" инструментов. Кэш сохранён на устройстве."); } catch(Exception parseError) { status.setText("MOEX ответила, но котировки не удалось обработать. Старые данные не заменены. ("+parseError.getMessage()+")"); new AlertDialog.Builder(this).setTitle("Ошибка данных MOEX").setMessage(parseError.getMessage()).setPositiveButton("OK",null).show(); } });
            } catch(Exception ex) {
                runOnUiThread(() -> status.setText("Не удалось подключиться к MOEX по HTTPS. Проверьте интернет, VPN, дату и время устройства. Сохранённые данные не удалены. ("+ex.getMessage()+")"));
            } finally { if(c!=null)c.disconnect(); }
        });
    }

    private void parseQuotes(JSONObject data) {
        try {
            JSONObject sec = data.getJSONObject("securities"), md = data.getJSONObject("marketdata");
            JSONArray sCols=sec.getJSONArray("columns"), sData=sec.getJSONArray("data");
            JSONArray mCols=md.getJSONArray("columns"), mData=md.getJSONArray("data");
            int ti=column(sCols,"SECID"), ni=column(sCols,"SHORTNAME");
            int mi=column(mCols,"SECID"), pi=column(mCols,"LAST"), ci=column(mCols,"CHANGE");
            if(ti<0||ni<0||mi<0||pi<0||ci<0) throw new IOException("MOEX вернула неполный набор колонок SECID/SHORTNAME/LAST/CHANGE");
            HashMap<String,JSONArray> prices=new HashMap<>();
            for(int i=0;i<mData.length();i++){ JSONArray r=mData.optJSONArray(i); if(r!=null) prices.put(r.optString(mi),r); }
            ArrayList<Stock> parsed=new ArrayList<>();
            for(int i=0;i<sData.length();i++){
                JSONArray r=sData.optJSONArray(i); if(r==null)continue;
                String ticker=r.optString(ti,""), name=r.optString(ni,ticker);
                if(ticker.isEmpty())continue;
                JSONArray q=prices.get(ticker); Object p=q==null?null:q.opt(pi), ch=q==null?null:q.opt(ci);
                double pct = Double.NaN;
                try { if(p!=null && p!=JSONObject.NULL && ch!=null && ch!=JSONObject.NULL) { double last=Double.parseDouble(p.toString()), delta=Double.parseDouble(ch.toString()); double prev=last-delta; if(prev>0) pct=(delta/prev)*100.0; } } catch(Exception ignored) {}
                parsed.add(new Stock(ticker,name,number(p),number(ch),pct));
            }
            if(parsed.isEmpty()) throw new IOException("MOEX вернула пустой список инструментов. Проверьте доступность ISS и параметры запроса.");
            parsed.sort((a,b)->a.ticker.compareTo(b.ticker));
            stocks.clear(); stocks.addAll(parsed);
            updateSearchSuggestions();
            renderAnalytics();
            renderPlans();
        } catch(Exception e) {
            throw new IllegalArgumentException("Не удалось разобрать ответ MOEX: "+e.getMessage(),e);
        }
    }
    private void updateSearchSuggestions() {
        if(search==null)return;
        ArrayList<String> options=new ArrayList<>();
        for(Stock st:stocks) options.add(st.ticker+" — "+st.name);
        searchAdapter=new ArrayAdapter<>(this,android.R.layout.simple_dropdown_item_1line,options);
        search.setAdapter(searchAdapter);
    }
    private int column(JSONArray a,String name) { for(int i=0;i<a.length();i++) if(name.equals(a.optString(i)))return i; return -1; }
    private String number(Object x) {
        if(x==null || x==JSONObject.NULL) return "—";
        try { return String.format(Locale.US,"%.2f",Double.parseDouble(x.toString())); } catch(Exception e){return "—";}
    }
    private void renderAnalytics() {
        if(analytics==null) return;
        analytics.removeAllViews();
        ArrayList<Stock> valid=new ArrayList<>(); int up=0, down=0, flat=0; double sum=0;
        for(Stock st:stocks) { if(Double.isNaN(st.changePct)) continue; valid.add(st); sum+=st.changePct; if(st.changePct>0.0001) up++; else if(st.changePct< -0.0001) down++; else flat++; }
        int n=valid.size();
        if(n==0) { analytics.addView(text("Нет данных для расчёта. Обновите котировки при открытом доступе к MOEX.",14,false)); return; }
        analytics.addView(text("Инструментов с котировками: "+n+"   •   Среднее изменение: "+String.format(Locale.US,"%+.2f%%",sum/n),15,true));
        analytics.addView(text("Растут: "+up+"   •   Снижаются: "+down+"   •   Без изменения: "+flat,14,false));
        ArrayList<Stock> ranked=new ArrayList<>(valid); ranked.sort((a,b)->Double.compare(b.changePct,a.changePct));
        analytics.addView(text("Лидеры роста",16,true));
        for(int i=0;i<Math.min(5,ranked.size());i++) { Stock st=ranked.get(i); analytics.addView(text((i+1)+". "+st.ticker+" — "+String.format(Locale.US,"%+.2f%%",st.changePct),14,false)); }
        analytics.addView(text("Лидеры снижения",16,true)); ranked.sort((a,b)->Double.compare(a.changePct,b.changePct));
        for(int i=0;i<Math.min(5,ranked.size());i++) { Stock st=ranked.get(i); analytics.addView(text((i+1)+". "+st.ticker+" — "+String.format(Locale.US,"%+.2f%%",st.changePct),14,false)); }
        analytics.addView(text("Кандидаты для наблюдения",16,true));
        int candidates=0;
        for(int i=0;i<ranked.size() && candidates<5;i++) {
            Stock st=ranked.get(i);
            if(st.changePct>0.0 && st.changePct<=3.0) {
                analytics.addView(text("• "+st.ticker+" — "+String.format(Locale.US,"%+.2f%%",st.changePct)+" за день",14,false));
                candidates++;
            }
        }
        if(candidates==0) analytics.addView(text("Сейчас нет бумаг с умеренным положительным изменением по текущему фильтру.",13,false));
        analytics.addView(text("Фильтр — только первичный сигнал по дневному изменению. Перед покупкой проверьте график, ликвидность, новости и риск. Рост за день сам по себе не означает, что бумагу стоит покупать.",12,false));
        analytics.addView(text("Изменение рассчитано относительно предыдущей цены закрытия. Это обзор текущего среза, не прогноз.",12,false));
    }

    private void render(String query) {
        list.removeAllViews();
        String q=query==null?"":query.trim().toLowerCase(Locale.ROOT);
        int shown=0;
        for(Stock s:stocks) {
            if(!q.isEmpty() && !s.ticker.toLowerCase(Locale.ROOT).contains(q) && !s.name.toLowerCase(Locale.ROOT).contains(q))continue;
            LinearLayout card=new LinearLayout(this); card.setOrientation(LinearLayout.VERTICAL);
            card.setPadding(dp(12),dp(8),dp(12),dp(8)); card.setBackgroundColor(0xffffffff);
            LinearLayout.LayoutParams cp=new LinearLayout.LayoutParams(-1,-2); cp.bottomMargin=dp(8); list.addView(card,cp);
            card.addView(text(s.ticker+"  ·  "+s.name,17,true));
            card.addView(text("Цена: "+s.price+" ₽     Изменение: "+s.change,14,false));
            String note=prefs.getString("note_"+s.ticker,"");
            TextView nt=text(note.isEmpty()?"Заметок пока нет": "Заметка: "+note,13,false);
            nt.setTextColor(0xff52606d); card.addView(nt);
            Button edit=new Button(this); edit.setText(note.isEmpty()?"Добавить заметку":"Изменить заметку");
            card.addView(edit); edit.setOnClickListener(v->editNote(s,nt,edit));
            Button analysis=new Button(this); analysis.setText("Полный анализ и рекомендация"); card.addView(analysis); analysis.setOnClickListener(v->analyzeStock(s));
            shown++; if(shown>=150)break;
        }
        if(shown==0) list.addView(text(stocks.isEmpty()?"Список пока пуст. Нажмите «Обновить котировки» при наличии интернета.":"Ничего не найдено. Проверьте тикер или название.",15,false));
    }
    private EditText field(String hint) {
        EditText e=new EditText(this); e.setSingleLine(true); e.setHint(hint);
        e.setInputType(android.text.InputType.TYPE_CLASS_TEXT);
        return e;
    }
    private EditText numericField(String hint) {
        EditText e=field(hint); e.setInputType(android.text.InputType.TYPE_CLASS_NUMBER|android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL);
        return e;
    }
    private double val(EditText e) {
        try { return Double.parseDouble(e.getText().toString().trim().replace(',','.')); } catch(Exception ex){ return 0; }
    }
    private double current(String ticker) {
        for(Stock st:stocks) if(st.ticker.equalsIgnoreCase(ticker)) {
            try { return Double.parseDouble(st.price.replace(',','.')); } catch(Exception ignored) {}
        }
        return Double.NaN;
    }
    private void loadPlans() {
        try {
            JSONArray a=new JSONArray(prefs.getString("candidates","[]"));
            for(int i=0;i<a.length();i++){JSONObject o=a.getJSONObject(i);Candidate c=new Candidate(o.getString("ticker"),o.optDouble("entry"),o.optDouble("stop"),o.optDouble("target"),o.optString("period","Среднесрочный"));if(c.entry>0&&(c.stop<=0||c.stop>=c.entry))c.stop=c.entry*0.92;if(c.entry>0&&(c.target<=c.entry))c.target=c.entry*1.16;c.score=o.optInt("score",0);c.recommendation=o.optString("recommendation","Не оценено");candidates.add(c);}
        } catch(Exception ignored) {}
        try {
            JSONArray a=new JSONArray(prefs.getString("holdings","[]"));
            for(int i=0;i<a.length();i++){JSONObject o=a.getJSONObject(i);Holding x=new Holding(o.getString("ticker"),o.optDouble("quantity"),o.optDouble("buy"),o.optDouble("stop"),o.optDouble("target"));if(x.buy>0&&(x.stop<=0||x.stop>=x.buy))x.stop=x.buy*0.92;if(x.buy>0&&(x.target<=x.buy))x.target=x.buy*1.16;holdings.add(x);}
        } catch(Exception ignored) {}
        // Сохраняем нормализованные уровни старых записей.
        savePlans();
    }
    private void savePlans() {
        try {
            JSONArray a=new JSONArray();
            for(Candidate c:candidates){JSONObject o=new JSONObject();o.put("ticker",c.ticker);o.put("entry",c.entry);o.put("stop",c.stop);o.put("target",c.target);o.put("period",c.period);o.put("score",c.score);o.put("recommendation",c.recommendation);a.put(o);}
            JSONArray h=new JSONArray();
            for(Holding x:holdings){JSONObject o=new JSONObject();o.put("ticker",x.ticker);o.put("quantity",x.quantity);o.put("buy",x.buy);o.put("stop",x.stop);o.put("target",x.target);h.put(o);}
            prefs.edit().putString("candidates",a.toString()).putString("holdings",h.toString()).apply();
        } catch(Exception ignored) {}
    }
    private void candidateDialog(Candidate existing) {
        LinearLayout box=new LinearLayout(this);box.setPadding(dp(16),dp(8),dp(16),0);box.setOrientation(LinearLayout.VERTICAL);
        EditText ticker=field("Тикер, например SBER"); EditText entry=numericField("Цена входа (₽, можно оставить пустой)");
        EditText stop=numericField("Стоп-цена (₽, можно рассчитать автоматически)"); EditText target=numericField("Цель (₽, можно рассчитать автоматически)");
        Spinner period=new Spinner(this);String[] periods={"Краткосрочный","Среднесрочный","Долгосрочный"};
        period.setAdapter(new ArrayAdapter<String>(this,android.R.layout.simple_spinner_dropdown_item,periods));
        box.addView(ticker);box.addView(new TextView(this){{setText("Период оценки");}});box.addView(period);box.addView(entry);box.addView(stop);box.addView(target);
        if(existing!=null){ticker.setText(existing.ticker);ticker.setEnabled(false);entry.setText(existing.entry==0?"":String.valueOf(existing.entry));stop.setText(existing.stop==0?"":String.valueOf(existing.stop));target.setText(existing.target==0?"":String.valueOf(existing.target));for(int i=0;i<periods.length;i++)if(periods[i].equals(existing.period))period.setSelection(i);}
        new AlertDialog.Builder(this).setTitle(existing==null?"Новый кандидат":"Изменить план входа").setView(box)
          .setPositiveButton("Сохранить",(d,w)->{
            String t=ticker.getText().toString().trim().toUpperCase(Locale.ROOT);
            double e=val(entry);if(e<=0)e=current(t);
            if(t.isEmpty()||Double.isNaN(e)||e<=0){Toast.makeText(this,"Укажите тикер и доступную цену входа",Toast.LENGTH_LONG).show();return;}
            Candidate c=new Candidate(t,e,val(stop),val(target),period.getSelectedItem().toString());
            if(c.stop<=0)c.stop=e*0.92;if(c.target<=0)c.target=e*1.16;
            if(c.stop>=e||c.target<=e){Toast.makeText(this,"Стоп должен быть ниже входа, а цель — выше входа",Toast.LENGTH_LONG).show();return;}
            if(existing!=null)candidates.remove(existing);candidates.add(c);savePlans();renderPlans();
          }).setNegativeButton("Отмена",null).show();
    }
    private void holdingDialog(Holding existing) {
        LinearLayout box=new LinearLayout(this);box.setPadding(dp(16),dp(8),dp(16),0);box.setOrientation(LinearLayout.VERTICAL);
        EditText ticker=field("Тикер, например SBER"); EditText qty=numericField("Количество акций (шт.)");
        EditText buy=numericField("Средняя цена покупки (₽)"); EditText stop=numericField("Стоп-цена выхода (₽, необязательно)");
        EditText target=numericField("Целевая цена выхода (₽, необязательно)");
        box.addView(ticker);box.addView(qty);box.addView(buy);box.addView(stop);box.addView(target);
        if(existing!=null){ticker.setText(existing.ticker);ticker.setEnabled(false);qty.setText(String.valueOf(existing.quantity));buy.setText(String.valueOf(existing.buy));stop.setText(existing.stop==0?"":String.valueOf(existing.stop));target.setText(existing.target==0?"":String.valueOf(existing.target));}
        new AlertDialog.Builder(this).setTitle(existing==null?"Добавить позицию":"Изменить позицию").setView(box)
          .setPositiveButton("Сохранить",(d,w)->{
            String t=ticker.getText().toString().trim().toUpperCase(Locale.ROOT);
            if(t.isEmpty()||val(qty)<=0||val(buy)<=0){Toast.makeText(this,"Укажите тикер, количество и цену покупки",Toast.LENGTH_LONG).show();return;}
            double b=val(buy),sl=val(stop),tp=val(target);
            if(sl<=0)sl=b*0.92;if(tp<=0)tp=b*1.16;
            if(sl>=b||tp<=b){Toast.makeText(this,"Стоп должен быть ниже цены покупки, а цель — выше неё",Toast.LENGTH_LONG).show();return;}
            Holding h=new Holding(t,val(qty),b,sl,tp);
            if(existing!=null)holdings.remove(existing);holdings.add(h);savePlans();renderPlans();
          }).setNegativeButton("Отмена",null).show();
    }
    private void renderPlans() {
        if(watchList==null||portfolioList==null)return;
        watchList.removeAllViews();portfolioList.removeAllViews();
        if(candidates.isEmpty())watchList.addView(text("Кандидатов пока нет. Добавьте тикер и плановую цену входа.",14,false));
        ArrayList<Candidate> rankedCandidates=new ArrayList<>(candidates);
        rankedCandidates.sort((a,b)->Integer.compare(b.score,a.score));
        int candidateRank=0;
        for(Candidate c:rankedCandidates){
            candidateRank++;
            double p=current(c.ticker);String signal=Double.isNaN(p)?"Нет котировки":p<=c.entry?"Цена входа достигнута или ниже": "Ожидание входа";
            if(c.stop>0&&!Double.isNaN(p)&&p<=c.stop)signal="Стоп-уровень достигнут";
            if(c.target>0&&!Double.isNaN(p)&&p>=c.target)signal="Цель достигнута";
            LinearLayout card=new LinearLayout(this);card.setOrientation(LinearLayout.VERTICAL);card.setPadding(dp(10),dp(6),dp(10),dp(6));card.setBackgroundColor(0xffffffff);watchList.addView(card);
            card.addView(text(candidateRank+". "+c.ticker+" • текущая цена: "+(Double.isNaN(p)?"—":number(p)),16,true));
            card.addView(text("Период: "+c.period+" • Оценка тренда: "+c.score+"/6",13,false));
            card.addView(text("Вход: "+number(c.entry)+" ₽ • Стоп: "+number(c.stop)+" ₽ • Цель: "+number(c.target)+" ₽",13,false));
            card.addView(text("Рекомендация: "+c.recommendation+" • Сигнал цены: "+signal,14,true));
            Button evaluate=new Button(this);evaluate.setText("Оценить по выбранному периоду");card.addView(evaluate);evaluate.setOnClickListener(v->analyzeCandidate(c));
            LinearLayout buttons=new LinearLayout(this);Button edit=new Button(this);edit.setText("Изменить");Button del=new Button(this);del.setText("Удалить");buttons.addView(edit);buttons.addView(del);card.addView(buttons);
            edit.setOnClickListener(v->candidateDialog(c));del.setOnClickListener(v->{candidates.remove(c);savePlans();renderPlans();});
        }
        if(holdings.isEmpty())portfolioList.addView(text("Портфель пуст. Добавьте фактически купленные акции.",14,false));
        double totalCost=0,totalValue=0,totalRiskCash=0;
        for(Holding h:new ArrayList<>(holdings)){
            double p=current(h.ticker);double cost=h.quantity*h.buy;totalCost+=cost;
            String currentText=Double.isNaN(p)?"—":number(p)+" ₽";
            String pnl=Double.isNaN(p)?"Нет котировки":String.format(Locale.US,"%+.2f ₽ (%+.2f%%)",(p-h.buy)*h.quantity,(p-h.buy)/h.buy*100);
            if(!Double.isNaN(p))totalValue+=p*h.quantity;
            if(h.stop>0)totalRiskCash+=Math.max(0,h.buy-h.stop)*h.quantity;
            String signal="Держать под наблюдением";
            if(!Double.isNaN(p)&&h.stop>0&&p<=h.stop)signal="Уровень стоп-выхода достигнут";
            else if(!Double.isNaN(p)&&h.target>0&&p>=h.target)signal="Целевая цена выхода достигнута";
            LinearLayout card=new LinearLayout(this);card.setOrientation(LinearLayout.VERTICAL);card.setPadding(dp(10),dp(6),dp(10),dp(6));card.setBackgroundColor(0xffffffff);portfolioList.addView(card);
            card.addView(text(h.ticker+" • "+h.quantity+" шт.",16,true));
            card.addView(text("Покупка: "+number(h.buy)+" ₽ • Сейчас: "+currentText,13,false));
            card.addView(text("Стоимость покупки: "+number(cost)+" ₽ • Результат: "+pnl,13,false));
            if(h.stop<=0)h.stop=h.buy*0.92;if(h.target<=0)h.target=h.buy*1.16;
            card.addView(text("Стоп-цена: "+number(h.stop)+" ₽ • Цель: "+number(h.target)+" ₽",13,true));
            double riskPct=h.buy>0?(h.buy-h.stop)/h.buy*100.0:0;
            double riskMoney=Math.max(0,h.buy-h.stop)*h.quantity;
            card.addView(text("Риск до стопа: "+number(riskMoney)+" ₽ ("+fmt(riskPct)+"% от цены покупки). Уровни по умолчанию — −8% / +16%; замените их после технической оценки.",11,false));
            card.addView(text("Контроль: "+signal,14,true));
            LinearLayout buttons=new LinearLayout(this);Button edit=new Button(this);edit.setText("Изменить");Button del=new Button(this);del.setText("Удалить");buttons.addView(edit);buttons.addView(del);card.addView(buttons);
            edit.setOnClickListener(v->holdingDialog(h));del.setOnClickListener(v->{holdings.remove(h);savePlans();renderPlans();});
        }
        if(!holdings.isEmpty()){
            portfolioList.addView(text("Вложено: "+number(totalCost)+" ₽ • Текущая стоимость по доступным котировкам: "+number(totalValue)+" ₽",14,true));
            double portfolioRiskPct=totalValue>0?totalRiskCash/totalValue*100.0:0;
            portfolioList.addView(text("Потенциальный убыток до установленных стопов: "+number(totalRiskCash)+" ₽ ("+fmt(portfolioRiskPct)+"% текущей стоимости портфеля). Это оценка по стопам, не максимальный возможный убыток.",13,true));
        }
    }

    private static class Candle { double open,high,low,close,volume; String date; }
    private ArrayList<Candle> fetchCandles(Stock stock,int interval,int days) throws Exception {
        Calendar cal=Calendar.getInstance(); cal.add(Calendar.DAY_OF_YEAR,-days);
        String from=String.format(Locale.US,"%tF",cal);
        ArrayList<Candle> result=new ArrayList<>();
        for(int page=0;page<10;page++) {
            String path="/iss/engines/stock/markets/shares/securities/"+URLEncoder.encode(stock.ticker,"UTF-8")+"/candles.json?from="+from+"&interval="+interval+"&start="+(page*500);
            JSONObject data=null; Exception last=null;
            for(String scheme:new String[]{"https"}) {
                HttpURLConnection c=null;
                try {
                    c=(HttpURLConnection)new URL(scheme+"://iss.moex.com"+path).openConnection();
                    c.setConnectTimeout(12000);c.setReadTimeout(25000);c.setRequestProperty("User-Agent","Prosperity-Android/1.0");
                    if(c.getResponseCode()!=200)throw new IOException("HTTP "+c.getResponseCode());
                    ByteArrayOutputStream out=new ByteArrayOutputStream();
                    try(InputStream in=c.getInputStream()){byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1)out.write(b,0,n);}
                    data=new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8));break;
                } catch(Exception e){last=e;} finally {if(c!=null)c.disconnect();}            }
            if(data==null) {
                if(page==0)throw new IOException("Не удалось получить свечи интервала "+interval+": "+(last==null?"нет ответа":last.getMessage()));
                break;
            }
            JSONObject block=data.getJSONObject("candles"); JSONArray cols=block.getJSONArray("columns"),rows=block.getJSONArray("data");
            int ci=column(cols,"close"),hi=column(cols,"high"),lo=column(cols,"low"),oi=column(cols,"open"),vi=column(cols,"volume"),di=column(cols,"begin");
            if(ci<0)throw new IOException("В ответе MOEX нет поля close");
            for(int i=0;i<rows.length();i++) {
                JSONArray r=rows.getJSONArray(i);if(r.isNull(ci))continue;
                Candle x=new Candle();x.close=r.optDouble(ci);x.high=hi>=0?r.optDouble(hi):x.close;x.low=lo>=0?r.optDouble(lo):x.close;
                x.open=oi>=0?r.optDouble(oi):x.close;x.volume=vi>=0?r.optDouble(vi):0;x.date=di>=0?r.optString(di):"";
                if(x.close>0)result.add(x);
            }
            if(rows.length()<500)break;
        }
        return result;
    }
    private void analyzeStock(Stock stock) {
        status.setText("Загружаю дневную, часовую и 10-минутную историю "+stock.ticker+"…");
        io.execute(() -> {
            try {
                ArrayList<Candle> daily=fetchCandles(stock,24,420);
                ArrayList<Candle> hourly=null,tenMinute=null;
                String hourlyError="",tenError="";
                try{hourly=fetchCandles(stock,60,120);}catch(Exception e){hourlyError=e.getMessage();}
                try{tenMinute=fetchCandles(stock,10,30);}catch(Exception e){tenError=e.getMessage();}
                final ArrayList<Candle> h=hourly, m=tenMinute;
                StringBuilder report=new StringBuilder(buildAnalysis(stock,daily,h,m));
                report.append("\n\n=== СРЕДНЕСРОЧНАЯ КАРТИНА: 1 ЧАС ===\n");
                report.append(h==null?"Часовые данные временно недоступны: "+hourlyError:buildTimeframeSummary(h,"часовой график"));
                report.append("\n\n=== КРАТКОСРОЧНАЯ КАРТИНА: 10 МИНУТ ===\n");
                report.append(m==null?"10-минутные данные временно недоступны: "+tenError:buildTimeframeSummary(m,"10-минутный график"));
                report.append("\n\nКАК ЧИТАТЬ СОВМЕСТНЫЙ СИГНАЛ\nДневной график показывает основной тренд, часовой — состояние движения внутри нескольких торговых сессий, 10-минутный — краткосрочный импульс и возможную точку входа. Наиболее согласованный сценарий — когда направления всех трёх периодов совпадают. Если периоды противоречат друг другу, это признак неопределённости: лучше дождаться подтверждения. Внутридневные колебания шумнее дневных и не должны перевешивать долгосрочную картину.");
                final String result=report.toString();
                runOnUiThread(()->{status.setText("Мультиинтервальный анализ "+stock.ticker+" готов. Дневных свечей: "+daily.size()+", часовых: "+(h==null?0:h.size())+", 10-минутных: "+(m==null?0:m.size())+".");new AlertDialog.Builder(this).setTitle("Аналитика: "+stock.ticker).setMessage(result).setPositiveButton("Понятно",null).show();});
            } catch(Exception e){runOnUiThread(()->{status.setText("Не удалось получить историю "+stock.ticker);new AlertDialog.Builder(this).setTitle("Анализ недоступен").setMessage(e.getMessage()+"\nПроверьте доступ к MOEX и повторите попытку.").setPositiveButton("OK",null).show();});}
        });
    }
    private void analyzeCandidate(Candidate c) {
        Stock stock=null;for(Stock x:stocks)if(x.ticker.equalsIgnoreCase(c.ticker)){stock=x;break;}
        if(stock==null){new AlertDialog.Builder(this).setMessage("Нет актуальной котировки "+c.ticker+". Обновите котировки MOEX.").setPositiveButton("OK",null).show();return;}
        final Stock selected=stock;status.setText("Оцениваю "+c.ticker+" по периоду: "+c.period+"…");
        io.execute(()->{
            try{
                int interval=c.period.startsWith("Кратко")?10:(c.period.startsWith("Средне")?60:24);
                int days=c.period.startsWith("Кратко")?30:(c.period.startsWith("Средне")?120:420);
                ArrayList<Candle>a=fetchCandles(selected,interval,days);
                if(a.size()<55)throw new IOException("Недостаточно истории для выбранного периода: "+a.size()+" свечей.");
                int n=a.size();double p=a.get(n-1).close,s20=sma(a,n,20),s50=sma(a,n,50),r=rsi(a,14);
                double atr=0;for(int i=n-14;i<n;i++){Candle x=a.get(i),pr=a.get(i-1);atr+=Math.max(x.high-x.low,Math.max(Math.abs(x.high-pr.close),Math.abs(x.low-pr.close)));}atr/=14;
                int score=timeframePoints(a);
                if(c.period.startsWith("Долго")){score=0;if(p>s20)score+=2;if(s20>s50)score+=2;if(n>=200&&p>sma(a,n,200))score+=2;if(r>75)score-=2;if(r<50)score--;}
                score=Math.max(-6,Math.min(6,score));
                double entry=p,stop=Math.max(0,p-1.5*atr),target=p+3.0*atr;
                double risk=entry-stop,reward=target-entry,rr=risk>0?reward/risk:0;
                String rec=(score>=4&&p>s50&&r<75&&rr>=1.5)?"ПОКУПАТЬ ПОСЛЕ ПОДТВЕРЖДЕНИЯ":(score>=1&&r<80)?"ЖДАТЬ ОТКАТА / ПОДТВЕРЖДЕНИЯ":"НЕ ПОКУПАТЬ — СЛАБЫЙ ТРЕНД ИЛИ ПОВЫШЕННЫЙ РИСК";
                c.entry=entry;c.stop=stop;c.target=target;c.score=score;c.recommendation=rec;savePlans();
                String report="Период: "+c.period+"\\nСвечей: "+n+"; данные: "+a.get(0).date+" — "+a.get(n-1).date+
                    "\\nТекущая цена: "+fmt(p)+" ₽\\nSMA20: "+fmt(s20)+" ₽; SMA50: "+fmt(s50)+" ₽; RSI14: "+fmt(r)+
                    "\\nОценка тренда: "+score+"/6\\nРиск/потенциал: 1:"+fmt(rr)+"\\nРекомендация: "+rec+"\\n\\nПлан: вход около "+fmt(entry)+" ₽; стоп "+fmt(stop)+" ₽; цель "+fmt(target)+" ₽."+
                    "\\nУровни рассчитаны по ATR выбранного интервала. Долгосрочный режим использует дневные свечи как приближение, недельная агрегация ещё не реализована. Это сценарная оценка, не гарантия результата.";
                runOnUiThread(()->{renderPlans();status.setText("Оценка кандидата "+c.ticker+" завершена.");new AlertDialog.Builder(this).setTitle("Рекомендация: "+c.ticker).setMessage(report).setPositiveButton("Понятно",null).show();});
            }catch(Exception e){runOnUiThread(()->{status.setText("Не удалось оценить "+c.ticker);new AlertDialog.Builder(this).setTitle("Анализ недоступен").setMessage(e.getMessage()).setPositiveButton("OK",null).show();});}
        });
    }

    private String buildTimeframeSummary(ArrayList<Candle> a,String label) {
        if(a==null||a.size()<20)return "Недостаточно истории для расчёта (нужно минимум 20 свечей, получено "+(a==null?0:a.size())+").";
        int n=a.size();double p=a.get(n-1).close,s20=sma(a,n,20),change5=(p/a.get(Math.max(0,n-6)).close-1)*100.0;
        double strength=a.size()>14?rsi(a,14):Double.NaN;
        String direction=p>s20&&change5>0?"восходящее":p<s20&&change5<0?"нисходящее":"боковое / смешанное";
        StringBuilder b=new StringBuilder();
        b.append("Свечей: ").append(n).append("; период данных: ").append(a.get(0).date).append(" — ").append(a.get(n-1).date).append(".\n");
        b.append("Последняя цена закрытия свечи: ").append(fmt(p)).append(" ₽. SMA20: ").append(fmt(s20)).append(" ₽. Изменение за последние 5 свечей: ").append(fmt(change5)).append("%.\n");
        b.append("Оценка направления: ").append(direction).append(". ");
        if(p>s20)b.append("Цена выше средней за 20 свечей — локальный фон положительный. ");
        else b.append("Цена ниже средней за 20 свечей — локальный фон слабый. ");
        if(change5>0)b.append("Последние свечи показывают положительный импульс. ");
        else if(change5<0)b.append("Последние свечи показывают отрицательный импульс. ");
        else b.append("За последние свечи выраженного изменения нет. ");
        if(!Double.isNaN(strength)){b.append("RSI(14): ").append(fmt(strength)).append(" — ");if(strength<30)b.append("зона возможной перепроданности; нужен разворот вверх.");else if(strength>70)b.append("зона перегрева; возможен откат.");else if(strength>=50)b.append("импульс умеренно положительный.");else b.append("импульс пока слабый.");}
        return b.toString();
    }
    private double sma(ArrayList<Candle> a,int end,int period) {if(end<period)return Double.NaN;double sum=0;for(int i=end-period;i<end;i++)sum+=a.get(i).close;return sum/period;}
    private double ema(ArrayList<Candle> a,int end,int period) {if(end<period)return Double.NaN;double v=0;for(int i=0;i<period;i++)v+=a.get(i).close;v/=period;double k=2.0/(period+1);for(int i=period;i<end;i++)v=a.get(i).close*k+v*(1-k);return v;}
    private double rsi(ArrayList<Candle> a,int period) {if(a.size()<=period)return Double.NaN;double up=0,dn=0;for(int i=1;i<=period;i++){double d=a.get(i).close-a.get(i-1).close;if(d>0)up+=d;else dn-=d;}up/=period;dn/=period;for(int i=period+1;i<a.size();i++){double d=a.get(i).close-a.get(i-1).close;up=(up*(period-1)+Math.max(0,d))/period;dn=(dn*(period-1)+Math.max(0,-d))/period;}if(dn==0)return 100;return 100-100/(1+up/dn);}
    private int timeframePoints(ArrayList<Candle> a) {
        if(a==null||a.size()<55)return -99;
        int n=a.size(); double p=a.get(n-1).close,s20=sma(a,n,20),s50=sma(a,n,50);
        double mom=(p/a.get(Math.max(0,n-6)).close-1.0)*100.0;
        double r=rsi(a,14); int v=0;
        if(p>s20)v+=2; if(s20>s50)v+=2; if(mom>0)v++; if(r>=50&&r<=70)v++; 
        if(r<30 && rsi(new ArrayList<Candle>(a.subList(0,n-1)),14)<30 && r>rsi(new ArrayList<Candle>(a.subList(0,n-1)),14))v++;
        if(p<s20)v-=2; if(s20<s50)v-=2; if(mom<0)v--; if(r>75)v-=2;
        return Math.max(-6,Math.min(6,v));
    }
    private String buildAnalysis(Stock st,ArrayList<Candle> a,ArrayList<Candle> hourly,ArrayList<Candle> tenMinute) {
        if(a.size()<200)return "Для полного анализа нужно не менее 200 дневных свечей. Получено: "+a.size()+".";
        int n=a.size();double p=a.get(n-1).close,s20=sma(a,n,20),s50=sma(a,n,50),s200=sma(a,n,200),r=rsi(a,14);
        double macd=ema(a,n,12)-ema(a,n,26),prevMacd=ema(a,n-1,12)-ema(a,n-1,26);
        double atr=0;for(int i=n-14;i<n;i++){Candle x=a.get(i),pr=a.get(i-1);atr+=Math.max(x.high-x.low,Math.max(Math.abs(x.high-pr.close),Math.abs(x.low-pr.close)));}atr/=14;
        double support=Double.MAX_VALUE,resistance=0,vol=0;int vc=0;
        for(int i=Math.max(0,n-20);i<n-1;i++){Candle x=a.get(i);support=Math.min(support,x.low);resistance=Math.max(resistance,x.high);if(x.volume>0){vol+=x.volume;vc++;}}
        double avgVol=vc==0?0:vol/vc,lastVol=a.get(n-1).volume;
        ArrayList<String> pros=new ArrayList<>(),cons=new ArrayList<>(); int daily=0;
        if(p>s20){daily+=2;pros.add("цена выше SMA20");}else{daily-=2;cons.add("цена ниже SMA20");}
        if(s20>s50){daily+=2;pros.add("SMA20 выше SMA50");}else{daily-=2;cons.add("SMA20 ниже SMA50");}
        if(p>s200){daily+=2;pros.add("цена выше SMA200");}else{daily-=2;cons.add("цена ниже SMA200");}
        if(macd>prevMacd){daily++;pros.add("MACD растёт");}else{daily--;cons.add("MACD снижается");}
        double prevR=rsi(new ArrayList<Candle>(a.subList(0,n-1)),14);
        if(r>=50&&r<=70){daily++;pros.add("RSI в положительной рабочей зоне");}
        else if(r>75){daily-=2;cons.add("RSI выше 75 — риск перегрева");}
        else if(r<30&&r>prevR){daily++;pros.add("RSI разворачивается вверх из зоны перепроданности");}
        else if(r<50){daily--;cons.add("RSI ниже 50 без подтверждённого разворота");}
        if(avgVol>0&&lastVol>avgVol*1.2&&p>a.get(n-2).close){daily++;pros.add("объём выше среднего при росте цены");}
        if(resistance>0&&(resistance-p)/p<0.015){daily--;cons.add("близко сопротивление — потенциал ограничен");}
        int hp=timeframePoints(hourly),mp=timeframePoints(tenMinute);
        double dNorm=Math.max(0,Math.min(100,50+daily*5.0));
        double hNorm=hp==-99?50:Math.max(0,Math.min(100,50+hp*50.0/6.0));
        double mNorm=mp==-99?50:Math.max(0,Math.min(100,50+mp*50.0/6.0));
        double quality=dNorm*0.50+hNorm*0.30+mNorm*0.20;
        boolean aligned=(daily>0&&hp!=-99&&hp>0&&mp!=-99&&mp>0);
        String verdict=quality>=70&&daily>=2&&aligned?"СИЛЬНЫЕ УСЛОВИЯ ДЛЯ НАБЛЮДЕНИЯ":(quality<35||daily<=-2)?"СЛАБЫЙ ФОН — НЕ СПЕШИТЬ":"НЕЙТРАЛЬНО — ЖДАТЬ ПОДТВЕРЖДЕНИЯ";
        double entry=Math.min(p-0.25*atr,Math.max(s20,support)); if(entry<=0||entry>p)entry=p-0.25*atr;
        double stop=Math.max(0,entry-1.5*atr),target=entry+3.0*atr;
        double riskPct=entry>0?(entry-stop)/entry*100:0, rewardPct=entry>0?(target-entry)/entry*100:0;
        StringBuilder b=new StringBuilder();
        b.append("ВЫВОД: ").append(verdict).append("\\nКачество условий: ").append(fmt(quality)).append("/100 (не вероятность прибыли).\\n");
        b.append("Веса: дневной 50%, часовой 30%, 10 минут 20%. Совпадение направлений: ").append(aligned?"да":"не подтверждено / часть данных отсутствует").append(".\\n");
        b.append("ДНЕВНЫЕ ПОКАЗАТЕЛИ\\nЦена: ").append(fmt(p)).append(" ₽; SMA20: ").append(fmt(s20)).append("; SMA50: ").append(fmt(s50)).append("; SMA200: ").append(fmt(s200)).append("\\n");
        b.append("RSI14: ").append(fmt(r)).append("; MACD: ").append(fmt(macd)).append("; ATR14: ").append(fmt(atr)).append(" ₽\\n");
        b.append("Поддержка: ").append(fmt(support)).append(" ₽; сопротивление: ").append(fmt(resistance)).append(" ₽\\n");
        b.append("Оценка дневного тренда: ").append(fmt(dNorm)).append("/100; часового: ").append(hp==-99?"нет данных":fmt(hNorm)+"/100").append("; 10-минутного: ").append(mp==-99?"нет данных":fmt(mNorm)+"/100").append(".\\n");
        if(avgVol>0)b.append("Объём последней сессии / средний: ").append(fmt(lastVol)).append(" / ").append(fmt(avgVol)).append("\\n");
        b.append("\\nПОДТВЕРЖДЕНИЯ\\n");for(String x:pros)b.append("＋ ").append(x).append("\\n");for(String x:cons)b.append("− ").append(x).append("\\n");
        b.append("\\nПЛАН (ориентир, не приказ)\\nЗона входа: ").append(fmt(entry)).append(" ₽; стоп: ").append(fmt(stop)).append(" ₽; цель: ").append(fmt(target)).append(" ₽\\n");
        b.append("Риск: ").append(fmt(riskPct)).append("%; потенциал: ").append(fmt(rewardPct)).append("%; R/R 1:2.\\n");
        b.append("Сценарий отменяется, если дневная цена закрытия ниже поддержки или MACD/тренд ухудшаются. Перед сделкой проверить ликвидность, спред, новости и размер позиции.");
        b.append("\\n\\nДанные MOEX ISS: ").append(a.get(0).date).append(" — ").append(a.get(n-1).date).append(". Часовой свечей: ").append(hourly==null?0:hourly.size()).append("; 10-минутных: ").append(tenMinute==null?0:tenMinute.size()).append(". Издержки и налоги не включены.");
        return b.toString();
    }
    private String fmt(double v){return Double.isNaN(v)?"н/д":String.format(Locale.US,"%.2f",v);}

    private void chooseBackupExport() {
        Intent i=new Intent(Intent.ACTION_CREATE_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE); i.setType("application/json");
        i.putExtra(Intent.EXTRA_TITLE,"prosperity-backup-"+new java.text.SimpleDateFormat("yyyyMMdd-HHmm",Locale.US).format(new Date())+".json");
        startActivityForResult(i,REQUEST_EXPORT_BACKUP);
    }
    private void chooseBackupImport() {
        Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE); i.setType("application/json");
        startActivityForResult(i,REQUEST_IMPORT_BACKUP);
    }
    @Override protected void onActivityResult(int requestCode,int resultCode,Intent data) {
        super.onActivityResult(requestCode,resultCode,data);
        if(resultCode!=RESULT_OK||data==null||data.getData()==null)return;
        android.net.Uri uri=data.getData();
        if(requestCode==REQUEST_EXPORT_BACKUP) {
            try {
                JSONObject backup=new JSONObject(); backup.put("app","ru.mos2.prosperity"); backup.put("schema",1);
                backup.put("createdAt",System.currentTimeMillis()); backup.put("preferences",new JSONObject(prefs.getAll()));
                try(OutputStream out=getContentResolver().openOutputStream(uri,"w")) {
                    if(out==null)throw new IOException("Не удалось открыть файл для записи");
                    out.write(backup.toString(2).getBytes(StandardCharsets.UTF_8)); out.flush();
                }
                Toast.makeText(this,"Резервная копия сохранена",Toast.LENGTH_LONG).show();
            } catch(Exception e) { Toast.makeText(this,"Ошибка экспорта: "+e.getMessage(),Toast.LENGTH_LONG).show(); }
        } else if(requestCode==REQUEST_IMPORT_BACKUP) {
            try {
                StringBuilder raw=new StringBuilder();
                try(InputStream in=getContentResolver().openInputStream(uri); BufferedReader reader=new BufferedReader(new InputStreamReader(in,StandardCharsets.UTF_8))) {
                    if(in==null)throw new IOException("Не удалось открыть файл");
                    String line; while((line=reader.readLine())!=null)raw.append(line);
                }
                JSONObject backup=new JSONObject(raw.toString());
                if(!"ru.mos2.prosperity".equals(backup.optString("app"))||backup.optInt("schema")!=1)throw new IOException("Файл не является резервной копией Процветания или имеет неподдерживаемый формат");
                JSONObject values=backup.getJSONObject("preferences");
                new AlertDialog.Builder(this).setTitle("Восстановить данные?")
                    .setMessage("Текущие локальные данные будут заменены данными из резервной копии. Перед импортом рекомендуется сохранить текущую копию.")
                    .setNegativeButton("Отмена",null).setPositiveButton("Восстановить",(dialog,which)->{
                        try {
                            SharedPreferences.Editor editor=prefs.edit().clear();
                            Iterator<String> keys=values.keys();
                            while(keys.hasNext()) { String key=keys.next(); Object value=values.get(key);
                                if(value==JSONObject.NULL)continue;
                                if(value instanceof String)editor.putString(key,(String)value);
                                else if(value instanceof Boolean)editor.putBoolean(key,(Boolean)value);
                                else if(value instanceof Number) { double n=((Number)value).doubleValue();
                                    if(n==Math.rint(n)&&n>=Integer.MIN_VALUE&&n<=Integer.MAX_VALUE)editor.putInt(key,(int)n);
                                    else if(n==Math.rint(n)&&n>=Long.MIN_VALUE&&n<=Long.MAX_VALUE)editor.putLong(key,(long)n);
                                    else editor.putFloat(key,(float)n);
                                }
                            }
                            editor.commit(); loadPlansAfterRestore(); showCached(); renderPlans(); render("");
                            Toast.makeText(this,"Данные восстановлены. Проверьте портфель и заметки.",Toast.LENGTH_LONG).show();
                        } catch(Exception e) { Toast.makeText(this,"Ошибка восстановления: "+e.getMessage(),Toast.LENGTH_LONG).show(); }
                    }).show();
            } catch(Exception e) { Toast.makeText(this,"Не удалось прочитать резервную копию: "+e.getMessage(),Toast.LENGTH_LONG).show(); }
        }
    }
    private void loadPlansAfterRestore() {
        candidates.clear(); holdings.clear(); loadPlans();
    }

    private void editNote(Stock s,TextView view,Button button) {
        EditText input=new EditText(this); input.setMinLines(3); input.setGravity(Gravity.TOP);
        input.setText(prefs.getString("note_"+s.ticker,""));
        new AlertDialog.Builder(this).setTitle("Заметка: "+s.ticker).setView(input)
            .setPositiveButton("Сохранить",(d,w)->{String n=input.getText().toString().trim(); prefs.edit().putString("note_"+s.ticker,n).apply(); view.setText(n.isEmpty()?"Заметок пока нет":"Заметка: "+n); button.setText(n.isEmpty()?"Добавить заметку":"Изменить заметку");})
            .setNegativeButton("Отмена",null).show();
    }
    @Override protected void onDestroy(){ super.onDestroy(); io.shutdown(); }
}
''', encoding="utf-8")

manifest.write_text('''<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
    <application
        android:allowBackup="false"
        android:label="@string/app_name"
        android:usesCleartextTraffic="false"
        android:theme="@style/AppTheme">
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:configChanges="orientation|screenSize|keyboardHidden">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
''', encoding="utf-8")
strings.parent.mkdir(parents=True, exist_ok=True)
strings.write_text("""<resources>
    <string name="app_name">Процветание</string>
</resources>
""", encoding="utf-8")
if gradle.exists():
    g = gradle.read_text(encoding="utf-8")
    import re
    g = re.sub(r'versionCode\s+\d+', 'versionCode 17', g)
    g = re.sub(r'versionName\s+"[^"]+"', 'versionName "3.12.1"', g)
    # Use assignment syntax for Android DSL properties (Gradle 10 compatibility).
    g = re.sub(r'(?m)^(\s*)(namespace|compileSdk|minSdk|targetSdk)\s+([^\n]+)$', r'\1\2 = \3', g)
    g = g.replace('applicationId "ru.mos2.app"', 'applicationId "ru.mos2.prosperity"')
    gradle.write_text(g, encoding="utf-8")
worker = java.parent / "PriceMonitorWorker.java"
worker.write_text(r'''package ru.mos2.app;

import android.Manifest;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Build;
import androidx.core.app.NotificationCompat;
import androidx.core.content.ContextCompat;
import androidx.work.Worker;
import androidx.work.WorkerParameters;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

public class PriceMonitorWorker extends Worker {
    public PriceMonitorWorker(Context context, WorkerParameters params) { super(context, params); }

    @Override public Result doWork() {
        try {
            JSONObject data = download();
            HashMap<String,Double> prices = parse(data);
            android.content.SharedPreferences p = getApplicationContext().getSharedPreferences("prosperity", Context.MODE_PRIVATE);
            JSONArray candidates = new JSONArray(p.getString("candidates","[]"));
            JSONArray holdings = new JSONArray(p.getString("holdings","[]"));
            for (int i=0;i<candidates.length();i++) {
                JSONObject o=candidates.getJSONObject(i); String t=o.optString("ticker");
                Double price=prices.get(t); if(price==null) continue;
                double entry=o.optDouble("entry"), stop=o.optDouble("stop"), target=o.optDouble("target");
                alert(p,t,"entry",price<=entry,"Цена входа достигнута: "+t+" — "+fmt(price)+" ₽");
                alert(p,t,"stop",stop>0&&price<=stop,"Стоп-уровень: "+t+" — "+fmt(price)+" ₽");
                alert(p,t,"target",target>0&&price>=target,"Цель достигнута: "+t+" — "+fmt(price)+" ₽");
            }
            for (int i=0;i<holdings.length();i++) {
                JSONObject o=holdings.getJSONObject(i); String t=o.optString("ticker");
                Double price=prices.get(t); if(price==null) continue;
                double stop=o.optDouble("stop"), target=o.optDouble("target");
                alert(p,t,"holding_stop",stop>0&&price<=stop,"Проверить выход по стопу: "+t+" — "+fmt(price)+" ₽");
                alert(p,t,"holding_target",target>0&&price>=target,"Целевая цена выхода: "+t+" — "+fmt(price)+" ₽");
            }
            return Result.success();
        } catch(Exception e) { return Result.retry(); }
    }

    private JSONObject download() throws Exception {
        String path="/iss/engines/stock/markets/shares/securities.json?iss.meta=off&iss.only=securities,marketdata&securities.columns=SECID,SHORTNAME&marketdata.columns=SECID,LAST,CHANGE&limit=1000";
        Exception last=null;
        for(String scheme:new String[]{"https"}) {
            HttpURLConnection c=null;
            try {
                c=(HttpURLConnection)new URL(scheme+"://iss.moex.com"+path).openConnection();
                c.setConnectTimeout(10000); c.setReadTimeout(15000); c.setRequestProperty("User-Agent","Prosperity-Android/1.0");
                if(c.getResponseCode()!=200) throw new IOException("HTTP "+c.getResponseCode());
                ByteArrayOutputStream out=new ByteArrayOutputStream();
                try(InputStream in=c.getInputStream()){byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1)out.write(b,0,n);}
                return new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8));
            } catch(Exception e){last=e;} finally {if(c!=null)c.disconnect();}
        }
        throw new IOException("MOEX unavailable",last);
    }

    private HashMap<String,Double> parse(JSONObject data) throws Exception {
        HashMap<String,Double> out=new HashMap<>();
        JSONObject md=data.getJSONObject("marketdata"); JSONArray cols=md.getJSONArray("columns"), rows=md.getJSONArray("data");
        int ti=-1,pi=-1;
        for(int i=0;i<cols.length();i++){if("SECID".equals(cols.optString(i)))ti=i;if("LAST".equals(cols.optString(i)))pi=i;}
        if(ti<0||pi<0) throw new IOException("MOEX response misses SECID/LAST columns");
        for(int i=0;i<rows.length();i++) {
            JSONArray row=rows.getJSONArray(i);
            String ticker=row.optString(ti,"").trim();
            if(ticker.isEmpty()) continue;
            Object raw=row.opt(pi);
            if(!(raw instanceof Number)) continue;
            double price=((Number)raw).doubleValue();
            if(!Double.isNaN(price)&&!Double.isInfinite(price)&&price>0) out.put(ticker,price);
        }
        return out;
    }

    private void alert(android.content.SharedPreferences prefs,String ticker,String kind,boolean condition,String message) {
        String key="alert_"+ticker+"_"+kind;
        if(!condition) { prefs.edit().putBoolean(key,false).apply(); return; }
        if(prefs.getBoolean(key,false)) return;
        Context context=getApplicationContext();
        if(Build.VERSION.SDK_INT>=33 && ContextCompat.checkSelfPermission(context,Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED) return;
        NotificationManager manager=(NotificationManager)context.getSystemService(Context.NOTIFICATION_SERVICE);
        if(manager==null) return;
        if(Build.VERSION.SDK_INT>=24&&!manager.areNotificationsEnabled()) return;
        String channel="prosperity_market_alerts";
        if(Build.VERSION.SDK_INT>=26) {
            NotificationChannel ch=new NotificationChannel(channel,"Сигналы по портфелю",NotificationManager.IMPORTANCE_DEFAULT);
            ch.setDescription("Уведомления о достижении ценовых уровней");
            manager.createNotificationChannel(ch);
        }
        NotificationCompat.Builder notification=new NotificationCompat.Builder(context,channel)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("Процветание").setContentText(message)
            .setStyle(new NotificationCompat.BigTextStyle().bigText(message))
            .setPriority(NotificationCompat.PRIORITY_DEFAULT).setAutoCancel(true);
        manager.notify((ticker+"_"+kind).hashCode(),notification.build());
        prefs.edit().putBoolean(key,true).apply();
    }

    private String fmt(double value) { return String.format(Locale.US,"%.2f",value); }
}
''', encoding="utf-8")
    g = g.replace('applicationId "ru.mos2.app"', 'applicationId "ru.mos2.prosperity"')
    gradle.write_text(g, encoding="utf-8")
worker = java.parent / "PriceMonitorWorker.java"
worker.write_text(r'''package ru.mos2.app;

import android.Manifest;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Build;
import androidx.core.app.NotificationCompat;
import androidx.core.content.ContextCompat;
import androidx.work.Worker;
import androidx.work.WorkerParameters;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

public class PriceMonitorWorker extends Worker {
    public PriceMonitorWorker(Context context, WorkerParameters params) { super(context, params); }

    @Override public Result doWork() {
        try {
            JSONObject data = download();
            HashMap<String,Double> prices = parse(data);
            android.content.SharedPreferences p = getApplicationContext().getSharedPreferences("prosperity", Context.MODE_PRIVATE);
            JSONArray candidates = new JSONArray(p.getString("candidates","[]"));
            JSONArray holdings = new JSONArray(p.getString("holdings","[]"));
            for (int i=0;i<candidates.length();i++) {
                JSONObject o=candidates.getJSONObject(i); String t=o.optString("ticker");
                Double price=prices.get(t); if(price==null) continue;
                double entry=o.optDouble("entry"), stop=o.optDouble("stop"), target=o.optDouble("target");
                alert(p,t,"entry",price<=entry,"Цена входа достигнута: "+t+" — "+fmt(price)+" ₽");
                alert(p,t,"stop",stop>0&&price<=stop,"Стоп-уровень: "+t+" — "+fmt(price)+" ₽");
                alert(p,t,"target",target>0&&price>=target,"Цель достигнута: "+t+" — "+fmt(price)+" ₽");
            }
            for (int i=0;i<holdings.length();i++) {
                JSONObject o=holdings.getJSONObject(i); String t=o.optString("ticker");
                Double price=prices.get(t); if(price==null) continue;
                double stop=o.optDouble("stop"), target=o.optDouble("target");
                alert(p,t,"holding_stop",stop>0&&price<=stop,"Проверить выход по стопу: "+t+" — "+fmt(price)+" ₽");
                alert(p,t,"holding_target",target>0&&price>=target,"Целевая цена выхода: "+t+" — "+fmt(price)+" ₽");
            }
            return Result.success();
        } catch(Exception e) { return Result.retry(); }
    }

    private JSONObject download() throws Exception {
        String path="/iss/engines/stock/markets/shares/securities.json?iss.meta=off&iss.only=securities,marketdata&securities.columns=SECID,SHORTNAME&marketdata.columns=SECID,LAST,CHANGE&limit=1000";
        Exception last=null;
        for(String scheme:new String[]{"https"}) {
            HttpURLConnection c=null;
            try {
                c=(HttpURLConnection)new URL(scheme+"://iss.moex.com"+path).openConnection();
                c.setConnectTimeout(10000); c.setReadTimeout(15000); c.setRequestProperty("User-Agent","Prosperity-Android/1.0");
                if(c.getResponseCode()!=200) throw new IOException("HTTP "+c.getResponseCode());
                ByteArrayOutputStream out=new ByteArrayOutputStream();
                try(InputStream in=c.getInputStream()){byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1)out.write(b,0,n);}
                return new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8));
            } catch(Exception e){last=e;} finally {if(c!=null)c.disconnect();}
        }
        throw new IOException("MOEX unavailable",last);
    }

    private HashMap<String,Double> parse(JSONObject data) throws Exception {
        HashMap<String,Double> out=new HashMap<>();
        JSONObject md=data.getJSONObject("marketdata"); JSONArray cols=md.getJSONArray("columns"), rows=md.getJSONArray("data");
        int ti=-1,pi=-1;
        for(int i=0;i<cols.length();i++){if("SECID".equals(cols.optString(i)))ti=i;if("LAST".equals(cols.optString(i)))pi=i;}
        if(ti<0||pi<0) throw new IOException("MOEX response misses SECID/LAST columns");
        for(int i=0;i<rows.length();i++) {
            JSONArray row=rows.getJSONArray(i);
            String ticker=row.optString(ti,"").trim();
            if(ticker.isEmpty()) continue;
            Object raw=row.opt(pi);
            if(!(raw instanceof Number)) continue;
            double price=((Number)raw).doubleValue();
            if(!Double.isNaN(price)&&!Double.isInfinite(price)&&price>0) out.put(ticker,price);
        }
        return out;
    }

    private void alert(android.content.SharedPreferences prefs,String ticker,String kind,boolean condition,String message) {
        String key="alert_"+ticker+"_"+kind;
        if(!condition) { prefs.edit().putBoolean(key,false).apply(); return; }
        if(prefs.getBoolean(key,false)) return;
        Context context=getApplicationContext();
        if(Build.VERSION.SDK_INT>=33 && ContextCompat.checkSelfPermission(context,Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED) return;
        NotificationManager manager=(NotificationManager)context.getSystemService(Context.NOTIFICATION_SERVICE);
        if(manager==null) return;
        if(Build.VERSION.SDK_INT>=24&&!manager.areNotificationsEnabled()) return;
        String channel="prosperity_market_alerts";
        if(Build.VERSION.SDK_INT>=26) {
            NotificationChannel ch=new NotificationChannel(channel,"Сигналы по портфелю",NotificationManager.IMPORTANCE_DEFAULT);
            ch.setDescription("Уведомления о достижении ценовых уровней");
            manager.createNotificationChannel(ch);
        }
        NotificationCompat.Builder notification=new NotificationCompat.Builder(context,channel)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("Процветание").setContentText(message)
            .setStyle(new NotificationCompat.BigTextStyle().bigText(message))
            .setPriority(NotificationCompat.PRIORITY_DEFAULT).setAutoCancel(true);
        manager.notify((ticker+"_"+kind).hashCode(),notification.build());
        prefs.edit().putBoolean(key,true).apply();
    }

    private String fmt(double value) { return String.format(Locale.US,"%.2f",value); }
}
''', encoding="utf-8")
