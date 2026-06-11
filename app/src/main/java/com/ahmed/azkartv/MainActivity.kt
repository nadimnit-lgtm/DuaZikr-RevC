package com.ahmed.azkartv

import android.Manifest
import android.annotation.SuppressLint
import android.app.UiModeManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.os.Bundle
import android.util.Base64
import android.view.KeyEvent
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.GeolocationPermissions
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import java.io.File
import androidx.webkit.WebViewAssetLoader

/**
 * Single-activity host for the bundled offline reading interface.
 *
 * Assets are served through WebViewAssetLoader over the secure
 * https://appassets.androidplatform.net origin. The web layer can fetch bundled
 * JSON normally while all file-system access remains disabled.
 *
 * Location is requested only after the web layer asks for geolocation, which
 * happens when automatic prayer location is used. First launch remains quiet.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private var pendingGeoOrigin: String? = null
    private var pendingGeoCallback: GeolocationPermissions.Callback? = null

    private fun isTelevision(): Boolean {
        val ui = getSystemService(Context.UI_MODE_SERVICE) as? UiModeManager
        return ui?.currentModeType == Configuration.UI_MODE_TYPE_TELEVISION
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        val assetLoader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()

        webView = WebView(this).apply {
            isFocusable = true
            isFocusableInTouchMode = true
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                allowFileAccess = false
                allowContentAccess = false
                @Suppress("DEPRECATION")
                allowFileAccessFromFileURLs = false
                @Suppress("DEPRECATION")
                allowUniversalAccessFromFileURLs = false
                loadWithOverviewMode = true
                useWideViewPort = true
                mediaPlaybackRequiresUserGesture = true
                cacheMode = WebSettings.LOAD_DEFAULT
                mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                setGeolocationEnabled(true)
            }

            addJavascriptInterface(ShareBridge(), "AzkarShare")

            webViewClient = object : WebViewClient() {
                override fun shouldInterceptRequest(
                    view: WebView, request: WebResourceRequest
                ): WebResourceResponse? = assetLoader.shouldInterceptRequest(request.url)
            }

            webChromeClient = object : WebChromeClient() {
                override fun onGeolocationPermissionsShowPrompt(
                    origin: String, callback: GeolocationPermissions.Callback
                ) {
                    if (origin != "https://appassets.androidplatform.net") {
                        callback.invoke(origin, false, false)
                        return
                    }

                    val granted = ContextCompat.checkSelfPermission(
                        this@MainActivity, Manifest.permission.ACCESS_COARSE_LOCATION
                    ) == PackageManager.PERMISSION_GRANTED

                    if (granted) {
                        callback.invoke(origin, true, false)
                        return
                    }

                    pendingGeoOrigin = origin
                    pendingGeoCallback = callback
                    ActivityCompat.requestPermissions(
                        this@MainActivity,
                        arrayOf(Manifest.permission.ACCESS_COARSE_LOCATION),
                        LOCATION_PERMISSION_REQUEST
                    )
                }
            }
        }

        setContentView(webView)

        val base = "https://appassets.androidplatform.net/assets/index.html"
        val url = if (isTelevision()) "$base?tv=1" else base
        webView.loadUrl(url)
        webView.requestFocus()

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                webView.evaluateJavascript(
                    "(window.onTvBack && window.onTvBack()) ? 'true' : 'false'"
                ) { result ->
                    if (result != "\"true\"" && result != "true") {
                        isEnabled = false
                        onBackPressedDispatcher.onBackPressed()
                        isEnabled = true
                    }
                }
            }
        })
    }


    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (this::webView.isInitialized && event.keyCode != KeyEvent.KEYCODE_BACK) {
            webView.requestFocus()
            if (webView.dispatchKeyEvent(event)) return true
        }
        return super.dispatchKeyEvent(event)
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != LOCATION_PERMISSION_REQUEST) return

        val granted = grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED
        val origin = pendingGeoOrigin ?: "https://appassets.androidplatform.net"
        pendingGeoCallback?.invoke(origin, granted, false)
        pendingGeoOrigin = null
        pendingGeoCallback = null
    }

    override fun onResume() {
        super.onResume()
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    override fun onPause() {
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        super.onPause()
    }

    override fun onDestroy() {
        pendingGeoCallback = null
        if (this::webView.isInitialized) {
            (webView.parent as? ViewGroup)?.removeView(webView)
            webView.destroy()
        }
        super.onDestroy()
    }

    inner class ShareBridge {
        @JavascriptInterface
        fun shareText(text: String?) {
            val cleanText = text.orEmpty().trim().take(12000)
            if (cleanText.isEmpty()) return
            runOnUiThread {
                val sendIntent = Intent(Intent.ACTION_SEND).apply {
                    type = "text/plain"
                    putExtra(Intent.EXTRA_TEXT, cleanText)
                }
                startActivity(Intent.createChooser(sendIntent, getString(R.string.app_name)))
            }
        }

        @JavascriptInterface
        fun sharePng(dataUrl: String?, text: String?) {
            val raw = dataUrl.orEmpty()
            if (!raw.startsWith("data:image/png;base64,")) {
                shareText(text)
                return
            }

            val safeText = text.orEmpty().trim().take(12000)
            val encoded = raw.substringAfter("data:image/png;base64,")
            if (encoded.length > 12_000_000) {
                shareText(safeText)
                return
            }

            runOnUiThread {
                try {
                    val bytes = Base64.decode(encoded, Base64.DEFAULT)
                    val shareDir = File(cacheDir, "shared_cards").apply { mkdirs() }
                    val imageFile = File(shareDir, "dua-zikr-card.png")
                    imageFile.writeBytes(bytes)

                    val uri = FileProvider.getUriForFile(
                        this@MainActivity,
                        "${packageName}.fileprovider",
                        imageFile
                    )

                    val sendIntent = Intent(Intent.ACTION_SEND).apply {
                        type = "image/png"
                        putExtra(Intent.EXTRA_STREAM, uri)
                        // Image-only share: the card already contains all required text,
                        // so no EXTRA_TEXT caption is attached (avoids duplication).
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    startActivity(Intent.createChooser(sendIntent, getString(R.string.app_name)))
                } catch (_: Exception) {
                    shareText(safeText)
                }
            }
        }
    }

    companion object {
        private const val LOCATION_PERMISSION_REQUEST = 1001
    }
}
