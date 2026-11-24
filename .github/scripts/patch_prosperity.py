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
import android.graphics.Typeface;
import android.view.Gravity;
import android.view.View;
import android.widget.*;
import android.Manifest;
import android.content.pm.PackageManager;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.work.Constraints;
import androidx.work.NetworkType;
import androidx.work.PeriodicWorkRequest;
import androidx.work.PeriodicWorkRequestBuilder;
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
    private EditText search;
    private TextView status;
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final ArrayList<Stock> stocks = new ArrayList<>();
    private static final String CACHE = "quotes_cache";
    private static class Stock {
        String ticker, name, price, change;
        double changePct;
        Stock(String t, String n, String p, String c, double pct) { ticker=t; name=n; price=p; change=c; changePct=pct; }
    }
    private static class Candidate {
        String ticker; double entry, stop, target;
        Candidate(String t,double e,double s,double g){ticker=t;entry=e;stop=s;target=g;}
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
        root.addView(text("Акции • котировки MOEX • заметки без сервера", 14, false));
        LinearLayout bar = new LinearLayout(this); bar.setOrientation(LinearLayout.HORIZONTAL);
        search = new EditText(this); search.setSingleLine(true); search.setHint("Тикер или название, например SBER");
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
            catch (Exception ignored) { status.setText("Нет сохранённых котировок. Подключитесь к интернету для первой загрузки."); }
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
                // Сначала пробуем HTTP/80: в некоторых сетях исходящий HTTPS/443 заблокирован.
                // Если HTTP не работает, пробуем обычный HTTPS/443.
                for (String scheme : new String[]{"http", "https"}) {
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
                if (data == null) throw new IOException("HTTP/80 и HTTPS/443 недоступны: "+(lastError==null?"неизвестная ошибка":lastError.getMessage()));
                final JSONObject result = data;
                prefs.edit().putString(CACHE,result.toString()).putLong("updated",System.currentTimeMillis()).apply();
                runOnUiThread(() -> { parseQuotes(result); render(search.getText().toString()); status.setText("Котировки MOEX обновлены: "+stocks.size()+" инструментов. Кэш сохранён на устройстве."); });
            } catch(Exception ex) {
                runOnUiThread(() -> status.setText("Нет соединения с MOEX. Кэш сохранён. Проверены порты 80 и 443. ("+ex.getMessage()+")"));
            } finally { if(c!=null)c.disconnect(); }
        });
    }

    private void parseQuotes(JSONObject data) {
        stocks.clear();
        try {
            JSONObject sec = data.getJSONObject("securities"), md = data.getJSONObject("marketdata");
            JSONArray sCols=sec.getJSONArray("columns"), sData=sec.getJSONArray("data");
            JSONArray mCols=md.getJSONArray("columns"), mData=md.getJSONArray("data");
            int ti=sCols.toString().indexOf("\"SECID\""); int ni=sCols.toString().indexOf("\"SHORTNAME\"");
            int mi=mCols.toString().indexOf("\"SECID\""); int pi=mCols.toString().indexOf("\"LAST\""); int ci=mCols.toString().indexOf("\"CHANGE\"");
            ti=column(sCols,"SECID"); ni=column(sCols,"SHORTNAME"); mi=column(mCols,"SECID"); pi=column(mCols,"LAST"); ci=column(mCols,"CHANGE");
            HashMap<String,JSONArray> prices=new HashMap<>();
            for(int i=0;i<mData.length();i++){ JSONArray r=mData.optJSONArray(i); if(r!=null) prices.put(r.optString(mi),r); }
            for(int i=0;i<sData.length();i++){
                JSONArray r=sData.optJSONArray(i); if(r==null)continue;
                String ticker=r.optString(ti,""), name=r.optString(ni,ticker);
                if(ticker.isEmpty())continue;
                JSONArray q=prices.get(ticker); Object p=q==null?null:q.opt(pi), ch=q==null?null:q.opt(ci);
                double pct = Double.NaN;
                try { if(p!=null && p!=JSONObject.NULL && ch!=null && ch!=JSONObject.NULL) { double last=Double.parseDouble(p.toString()), delta=Double.parseDouble(ch.toString()); double prev=last-delta; if(prev>0) pct=(delta/prev)*100.0; } } catch(Exception ignored) {}
                stocks.add(new Stock(ticker,name,number(p),number(ch),pct));
            }
            stocks.sort((a,b)->a.ticker.compareTo(b.ticker));
            renderAnalytics();
            renderPlans();
        } catch(Exception ignored) {}
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
            for(int i=0;i<a.length();i++){JSONObject o=a.getJSONObject(i);candidates.add(new Candidate(o.getString("ticker"),o.optDouble("entry"),o.optDouble("stop"),o.optDouble("target")));}
        } catch(Exception ignored) {}
        try {
            JSONArray a=new JSONArray(prefs.getString("holdings","[]"));
            for(int i=0;i<a.length();i++){JSONObject o=a.getJSONObject(i);holdings.add(new Holding(o.getString("ticker"),o.optDouble("quantity"),o.optDouble("buy"),o.optDouble("stop"),o.optDouble("target")));}
        } catch(Exception ignored) {}
    }
    private void savePlans() {
        try {
            JSONArray a=new JSONArray();
            for(Candidate c:candidates){JSONObject o=new JSONObject();o.put("ticker",c.ticker);o.put("entry",c.entry);o.put("stop",c.stop);o.put("target",c.target);a.put(o);}
            JSONArray h=new JSONArray();
            for(Holding x:holdings){JSONObject o=new JSONObject();o.put("ticker",x.ticker);o.put("quantity",x.quantity);o.put("buy",x.buy);o.put("stop",x.stop);o.put("target",x.target);h.put(o);}
            prefs.edit().putString("candidates",a.toString()).putString("holdings",h.toString()).apply();
        } catch(Exception ignored) {}
    }
    private void candidateDialog(Candidate existing) {
        LinearLayout box=new LinearLayout(this);box.setPadding(dp(16),dp(8),dp(16),0);box.setOrientation(LinearLayout.VERTICAL);
        EditText ticker=field("Тикер, например SBER"); EditText entry=numericField("Цена входа (₽)");
        EditText stop=numericField("Стоп-цена (₽, необязательно)"); EditText target=numericField("Цель / цена выхода (₽, необязательно)");
        box.addView(ticker);box.addView(entry);box.addView(stop);box.addView(target);
        if(existing!=null){ticker.setText(existing.ticker);ticker.setEnabled(false);entry.setText(existing.entry==0?"":String.valueOf(existing.entry));stop.setText(existing.stop==0?"":String.valueOf(existing.stop));target.setText(existing.target==0?"":String.valueOf(existing.target));}
        new AlertDialog.Builder(this).setTitle(existing==null?"Новый кандидат":"Изменить план входа").setView(box)
          .setPositiveButton("Сохранить",(d,w)->{
            String t=ticker.getText().toString().trim().toUpperCase(Locale.ROOT);
            if(t.isEmpty()||val(entry)<=0){Toast.makeText(this,"Укажите тикер и цену входа",Toast.LENGTH_LONG).show();return;}
            Candidate c=new Candidate(t,val(entry),val(stop),val(target));
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
            Holding h=new Holding(t,val(qty),val(buy),val(stop),val(target));
            if(existing!=null)holdings.remove(existing);holdings.add(h);savePlans();renderPlans();
          }).setNegativeButton("Отмена",null).show();
    }
    private void renderPlans() {
        if(watchList==null||portfolioList==null)return;
        watchList.removeAllViews();portfolioList.removeAllViews();
        if(candidates.isEmpty())watchList.addView(text("Кандидатов пока нет. Добавьте тикер и плановую цену входа.",14,false));
        for(Candidate c:new ArrayList<>(candidates)){
            double p=current(c.ticker);String signal=Double.isNaN(p)?"Нет котировки":p<=c.entry?"Цена входа достигнута или ниже": "Ожидание входа";
            if(c.stop>0&&!Double.isNaN(p)&&p<=c.stop)signal="Стоп-уровень достигнут";
            if(c.target>0&&!Double.isNaN(p)&&p>=c.target)signal="Цель достигнута";
            LinearLayout card=new LinearLayout(this);card.setOrientation(LinearLayout.VERTICAL);card.setPadding(dp(10),dp(6),dp(10),dp(6));card.setBackgroundColor(0xffffffff);watchList.addView(card);
            card.addView(text(c.ticker+" • текущая цена: "+(Double.isNaN(p)?"—":number(p)),16,true));
            card.addView(text("Вход: "+number(c.entry)+" ₽ • Стоп: "+(c.stop>0?number(c.stop):"—")+" • Цель: "+(c.target>0?number(c.target):"—"),13,false));
            card.addView(text("Сигнал: "+signal,14,true));
            LinearLayout buttons=new LinearLayout(this);Button edit=new Button(this);edit.setText("Изменить");Button del=new Button(this);del.setText("Удалить");buttons.addView(edit);buttons.addView(del);card.addView(buttons);
            edit.setOnClickListener(v->candidateDialog(c));del.setOnClickListener(v->{candidates.remove(c);savePlans();renderPlans();});
        }
        if(holdings.isEmpty())portfolioList.addView(text("Портфель пуст. Добавьте фактически купленные акции.",14,false));
        double totalCost=0,totalValue=0;
        for(Holding h:new ArrayList<>(holdings)){
            double p=current(h.ticker);double cost=h.quantity*h.buy;totalCost+=cost;
            String currentText=Double.isNaN(p)?"—":number(p)+" ₽";
            String pnl=Double.isNaN(p)?"Нет котировки":String.format(Locale.US,"%+.2f ₽ (%+.2f%%)",(p-h.buy)*h.quantity,(p-h.buy)/h.buy*100);
            if(!Double.isNaN(p))totalValue+=p*h.quantity;
            String signal="Держать под наблюдением";
            if(!Double.isNaN(p)&&h.stop>0&&p<=h.stop)signal="Уровень стоп-выхода достигнут";
            else if(!Double.isNaN(p)&&h.target>0&&p>=h.target)signal="Целевая цена выхода достигнута";
            LinearLayout card=new LinearLayout(this);card.setOrientation(LinearLayout.VERTICAL);card.setPadding(dp(10),dp(6),dp(10),dp(6));card.setBackgroundColor(0xffffffff);portfolioList.addView(card);
            card.addView(text(h.ticker+" • "+h.quantity+" шт.",16,true));
            card.addView(text("Покупка: "+number(h.buy)+" ₽ • Сейчас: "+currentText,13,false));
            card.addView(text("Стоимость покупки: "+number(cost)+" ₽ • Результат: "+pnl,13,false));
            card.addView(text("Выход: стоп "+(h.stop>0?number(h.stop):"—")+" ₽ / цель "+(h.target>0?number(h.target):"—")+" ₽",13,false));
            card.addView(text("Контроль: "+signal,14,true));
            LinearLayout buttons=new LinearLayout(this);Button edit=new Button(this);edit.setText("Изменить");Button del=new Button(this);del.setText("Удалить");buttons.addView(edit);buttons.addView(del);card.addView(buttons);
            edit.setOnClickListener(v->holdingDialog(h));del.setOnClickListener(v->{holdings.remove(h);savePlans();renderPlans();});
        }
        if(!holdings.isEmpty())portfolioList.addView(text("Вложено: "+number(totalCost)+" ₽ • Текущая стоимость по доступным котировкам: "+number(totalValue)+" ₽",14,true));
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
        android:usesCleartextTraffic="true"
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
    g = re.sub(r'versionCode\s+\d+', 'versionCode 9', g)
    g = re.sub(r'versionName\s+"[^"]+"', 'versionName "3.5.0"', g)
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
        for(String scheme:new String[]{"http","https"}) {
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
        if(ti<0||pi<0)return out;
        for(int i=0;i<rows.length();i++){JSONArray r=rows.getJSONArray(i);Object v=r.opt(pi);if(v!=null&&v!=JSONObject.NULL)try{out.put(r.optString(ti),Double.parseDouble(v.toString()));}catch(Exception ignored){}}
        return out;
    }

    private void alert(android.content.SharedPreferences p,String ticker,String rule,boolean active,String message) {
        String key="alert_"+ticker+"_"+rule; boolean was=p.getBoolean(key,false);
        if(!active){if(was)p.edit().putBoolean(key,false).apply();return;}
        if(was)return;
        p.edit().putBoolean(key,true).apply();
        Context c=getApplicationContext();
        if(Build.VERSION.SDK_INT>=33 && ContextCompat.checkSelfPermission(c,Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)return;
        NotificationManager nm=(NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE);
        if(Build.VERSION.SDK_INT>=26)nm.createNotificationChannel(new NotificationChannel("prosperity_alerts","Сигналы Процветания",NotificationManager.IMPORTANCE_HIGH));
        NotificationCompat.Builder b=new NotificationCompat.Builder(c,"prosperity_alerts")
            .setSmallIcon(c.getApplicationInfo().icon).setContentTitle("Процветание — ценовой сигнал")
            .setContentText(message).setStyle(new NotificationCompat.BigTextStyle().bigText(message))
            .setPriority(NotificationCompat.PRIORITY_HIGH).setAutoCancel(true);
        nm.notify((ticker+"_"+rule).hashCode(),b.build());
    }
    private String fmt(double v){return String.format(Locale.US,"%.2f",v);}
}
''', encoding="utf-8")

print("Patched standalone Prosperity Android app")
