package com.priviworld.heyjose;

import android.app.Activity;
import android.os.Bundle;
import android.content.Intent;
import android.net.Uri;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;

public class MainActivity extends Activity {
  private WebView web;
  private static final String HOME = "https://jose-site.onrender.com/";
  @Override public void onCreate(Bundle state) {
    super.onCreate(state);
    web = new WebView(this);
    web.getSettings().setJavaScriptEnabled(true);
    web.getSettings().setDomStorageEnabled(true);
    web.getSettings().setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
    web.setWebViewClient(new WebViewClient() {
      @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
        Uri uri = request.getUrl();
        String host = uri.getHost();
        if ("https".equals(uri.getScheme()) && ("jose-site.onrender.com".equals(host) || "jose-backend-vbuu.onrender.com".equals(host))) return false;
        try { startActivity(new Intent(Intent.ACTION_VIEW, uri)); } catch (Exception ignored) {}
        return true;
      }
    });
    setContentView(web);
    web.loadUrl(HOME);
  }
  @Override public void onBackPressed() { if (web != null && web.canGoBack()) web.goBack(); else super.onBackPressed(); }
  @Override protected void onDestroy() { if(web != null) { web.destroy(); web = null; } super.onDestroy(); }
}
