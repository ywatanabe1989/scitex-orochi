// @ts-nocheck
// Migrated classic-script file. Types intentionally loose during
// the big-bang JS-to-TS bundle migration. Narrow later, per-file.
/* Password requirements live validation — matches scitex.ai rules */
(function () {
  var password = document.getElementById("id_password");
  var password2 = document.getElementById("id_password2");
  if (!password) return;

  var rules = {
    "rule-length": function (p) {
      return p.length >= 8;
    },
    "rule-lowercase": function (p) {
      return /[a-z]/.test(p);
    },
    "rule-uppercase": function (p) {
      return /[A-Z]/.test(p);
    },
    "rule-number": function (p) {
      return /\d/.test(p);
    },
    "rule-special": function (p) {
      return /[^a-zA-Z0-9]/.test(p);
    },
    "rule-match": function (p) {
      return p.length > 0 && password2 && p === password2.value;
    },
  };

  function update() {
    var val = password.value;
    for (var id in rules) {
      var el = document.getElementById(id);
      if (!el) continue;
      var met = rules[id](val);
      el.classList.toggle("met", met);
      el.classList.toggle("unmet", !met);
    }
  }

  password.addEventListener("input", update);
  if (password2) {
    password2.addEventListener("input", update);
  }
})();
