// Language switch: English by default; Turkish for Turkish browsers, ?lang=tr or #tr.
(function () {
  var supported = ['en', 'tr'];
  var q = new URLSearchParams(location.search).get('lang') || location.hash.replace('#', '');
  var stored = null;
  try { stored = localStorage.getItem('jiglume.lang'); } catch (e) {}
  var nav = (navigator.language || 'en').slice(0, 2).toLowerCase();
  var lang = [q, stored, nav].find(function (l) { return supported.indexOf(l) >= 0; }) || 'en';
  function apply(l) {
    document.documentElement.lang = l;
    document.querySelectorAll('.langs button').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.set === l));
    });
    var t = document.querySelector('meta[name="title-' + l + '"]');
    if (t) document.title = t.content;
  }
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.langs button').forEach(function (b) {
      b.addEventListener('click', function () {
        try { localStorage.setItem('jiglume.lang', b.dataset.set); } catch (e) {}
        apply(b.dataset.set);
      });
    });
    apply(lang);
  });
  document.documentElement.lang = lang;
})();
