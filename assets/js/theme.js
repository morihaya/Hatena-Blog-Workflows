// ヘッダーのライト/ダーク切り替え。
// 選択は localStorage に残し、次の表示では head の先頭スクリプトが反映する。
(function () {
  var button = document.querySelector(".theme-toggle");
  if (!button) return;

  var root = document.documentElement;
  var media = window.matchMedia("(prefers-color-scheme: dark)");

  function current() {
    return root.dataset.theme || (media.matches ? "dark" : "light");
  }

  function label() {
    button.setAttribute(
      "aria-label",
      current() === "dark" ? "ライトモードに切り替える" : "ダークモードに切り替える"
    );
  }

  button.addEventListener("click", function () {
    var next = current() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch (e) {}
    label();
  });

  // 手動選択がまだない間は OS 設定の変化にそのまま追従する
  media.addEventListener("change", label);
  label();
})();
