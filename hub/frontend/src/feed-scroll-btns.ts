// @ts-nocheck
/* Feed overlay scroll buttons — top / bottom */
(function () {
  function init() {
    var feed = document.getElementById("messages");
    var btnTop = document.getElementById("feed-scroll-top");
    var btnBottom = document.getElementById("feed-scroll-bottom");
    if (!feed || !btnTop || !btnBottom) return;

    function update() {
      var st = feed.scrollTop;
      var max = feed.scrollHeight - feed.clientHeight;
      btnTop.classList.toggle("visible", st > 80);
      btnBottom.classList.toggle("visible", max - st > 80);
    }

    feed.addEventListener("scroll", update, { passive: true });
    /* Also update when new messages arrive */
    new MutationObserver(update).observe(feed, { childList: true, subtree: false });
    update();

    btnTop.addEventListener("click", function () {
      feed.scrollTo({ top: 0, behavior: "smooth" });
    });
    btnBottom.addEventListener("click", function () {
      feed.scrollTo({ top: feed.scrollHeight, behavior: "smooth" });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
