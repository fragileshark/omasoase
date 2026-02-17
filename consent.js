// GDPR Cookie Consent Banner for omasoase.de
(function() {
    if (localStorage.getItem('omasoase_consent')) return;

    // Block GA4 until consent
    window['ga-disable-G-FX9ZFMQSEM'] = true;

    var banner = document.createElement('div');
    banner.id = 'cookieBanner';
    banner.innerHTML =
        '<div style="max-width:900px;margin:0 auto;display:flex;align-items:center;gap:16px;flex-wrap:wrap">' +
            '<p style="flex:1;min-width:200px;margin:0;font-size:14px;line-height:1.5">' +
                'Wir verwenden Cookies, um diese Website zu verbessern. ' +
                '<a href="/datenschutz.html" style="color:#8471a0;text-decoration:underline">Mehr erfahren</a>' +
            '</p>' +
            '<div style="display:flex;gap:8px">' +
                '<button id="consentReject" style="padding:8px 20px;border:1px solid #ccc;border-radius:6px;background:#fff;font-size:14px;cursor:pointer;font-family:inherit">Nur notwendige</button>' +
                '<button id="consentAccept" style="padding:8px 20px;border:none;border-radius:6px;background:#6b5b7b;color:#fff;font-size:14px;cursor:pointer;font-family:inherit">Alle akzeptieren</button>' +
            '</div>' +
        '</div>';

    banner.style.cssText = 'position:fixed;bottom:0;left:0;right:0;background:#fff;border-top:1px solid #e0e0e0;padding:16px 24px;z-index:10000;box-shadow:0 -2px 10px rgba(0,0,0,0.1);font-family:Inter,sans-serif';

    document.body.appendChild(banner);

    document.getElementById('consentAccept').onclick = function() {
        localStorage.setItem('omasoase_consent', 'all');
        window['ga-disable-G-FX9ZFMQSEM'] = false;
        // Re-init GA4
        if (typeof gtag === 'function') {
            gtag('consent', 'update', { analytics_storage: 'granted' });
        }
        banner.remove();
    };

    document.getElementById('consentReject').onclick = function() {
        localStorage.setItem('omasoase_consent', 'essential');
        banner.remove();
    };
})();
