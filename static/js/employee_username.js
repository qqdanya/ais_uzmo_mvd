(function () {
  const TRANSLIT_MAP = {
    а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "e", ж: "zh",
    з: "z", и: "i", й: "i", к: "k", л: "l", м: "m", н: "n", о: "o",
    п: "p", р: "r", с: "s", т: "t", у: "u", ф: "f", х: "h", ц: "ts",
    ч: "ch", ш: "sh", щ: "sch", ъ: "", ы: "y", ь: "", э: "e", ю: "yu", я: "ya",
  };

  function transliterate(value) {
    return String(value || "")
      .trim()
      .toLocaleLowerCase("ru-RU")
      .split("")
      .map((char) => TRANSLIT_MAP[char] ?? char)
      .join("")
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/_+/g, "_")
      .replace(/^_+|_+$/g, "");
  }

  function candidateUsernames(lastName, firstName, middleName) {
    const last = transliterate(lastName);
    const first = transliterate(firstName);
    const middle = transliterate(middleName);
    const candidates = [];
    if (last) {
      candidates.push(last);
      if (first) {
        candidates.push(`${last}_${first}`);
        if (middle) {
          candidates.push(`${last}_${first}_${middle}`);
        }
      }
    }
    return candidates.length ? candidates : ["user"];
  }

  function uniqueUsername(candidates, existingUsernames) {
    const existing = new Set(existingUsernames.map((item) => String(item || "").toLocaleLowerCase("en-US")));
    for (const candidate of candidates) {
      if (!existing.has(candidate.toLocaleLowerCase("en-US"))) {
        return candidate;
      }
    }
    const base = candidates[candidates.length - 1] || "user";
    let suffix = 2;
    while (existing.has(`${base}_${suffix}`.toLocaleLowerCase("en-US"))) {
      suffix += 1;
    }
    return `${base}_${suffix}`;
  }

  function readExistingUsernames() {
    const script = document.getElementById("employee-existing-usernames");
    if (!script) return [];
    try {
      const parsed = JSON.parse(script.textContent || "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  }

  function initEmployeeUsernameGenerator() {
    const form = document.querySelector("[data-employee-username-generator]");
    if (!form) return;
    const lastName = form.querySelector("#id_last_name");
    const firstName = form.querySelector("#id_first_name");
    const middleName = form.querySelector("#id_middle_name");
    const username = form.querySelector("#id_username");
    if (!lastName || !firstName || !middleName || !username) return;

    const existingUsernames = readExistingUsernames();
    let lastGenerated = username.value.trim();
    let manuallyChanged = Boolean(lastGenerated);

    username.addEventListener("input", () => {
      const value = username.value.trim();
      manuallyChanged = Boolean(value && value !== lastGenerated);
      if (!value) {
        manuallyChanged = false;
      }
    });

    function refreshUsername() {
      if (manuallyChanged) return;
      const generated = uniqueUsername(
        candidateUsernames(lastName.value, firstName.value, middleName.value),
        existingUsernames,
      );
      username.value = generated;
      lastGenerated = generated;
    }

    [lastName, firstName, middleName].forEach((input) => {
      input.addEventListener("input", refreshUsername);
      input.addEventListener("change", refreshUsername);
    });

    if (!username.value.trim()) {
      refreshUsername();
    }
  }

  document.addEventListener("DOMContentLoaded", initEmployeeUsernameGenerator);
})();
