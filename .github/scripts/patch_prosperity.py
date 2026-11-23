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
    private LinearLayout list, root;
    private EditText search;
    private TextView status;
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final ArrayList<Stock> stocks = new ArrayList<>();
    private static final String CACHE = "quotes_cache";
    private static class Stock {
        String ticker, name, price, change;
        Stock(String t, String n, String p, String c) { ticker=t; name=n; price=p; change=c; }
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("prosperity", MODE_PRIVATE);
        buildScreen();
        showCached();
        refreshQuotes();
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
        root.addView(text("Мои акции", 20, true));
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
                URL url = new URL("https://iss.moex.com/iss/engines/stock/markets/shares/securities.json?iss.meta=off&iss.only=securities,marketdata&securities.columns=SECID,SHORTNAME&marketdata.columns=SECID,LAST,CHANGE&limit=1000");
                c = (HttpURLConnection)url.openConnection(); c.setConnectTimeout(15000); c.setReadTimeout(20000);
                c.setRequestProperty("User-Agent","Prosperity-Android/1.0"); c.setRequestProperty("Accept","application/json");
                if (c.getResponseCode()!=200) throw new IOException("HTTP "+c.getResponseCode());
                ByteArrayOutputStream out = new ByteArrayOutputStream();
                try(InputStream in=c.getInputStream()) { byte[] b=new byte[8192]; int n; while((n=in.read(b))!=-1) out.write(b,0,n); }
                JSONObject data = new JSONObject(new String(out.toByteArray(), StandardCharsets.UTF_8));
                prefs.edit().putString(CACHE,data.toString()).putLong("updated",System.currentTimeMillis()).apply();
                runOnUiThread(() -> { parseQuotes(data); render(search.getText().toString()); status.setText("Котировки MOEX обновлены: "+stocks.size()+" инструментов. Кэш сохранён на устройстве."); });
            } catch(Exception ex) {
                runOnUiThread(() -> status.setText("Нет соединения с MOEX. Используются сохранённые данные, если они есть. ("+ex.getMessage()+")"));
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
                stocks.add(new Stock(ticker,name,number(p),number(ch)));
            }
            stocks.sort((a,b)->a.ticker.compareTo(b.ticker));
        } catch(Exception ignored) {}
    }
    private int column(JSONArray a,String name) { for(int i=0;i<a.length();i++) if(name.equals(a.optString(i)))return i; return -1; }
    private String number(Object x) {
        if(x==null || x==JSONObject.NULL) return "—";
        try { return String.format(Locale.US,"%.2f",Double.parseDouble(x.toString())); } catch(Exception e){return "—";}
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
    g = g.replace('versionCode 3', 'versionCode 4').replace('versionName "2.0.0"', 'versionName "3.0.0"')
    gradle.write_text(g, encoding="utf-8")
print("Patched standalone Prosperity Android app")
