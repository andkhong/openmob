// The signed-out landing page's only script (it runs under a strict CSP: no inline code anywhere on the page).
// Loaded in <head> without defer, so the saved theme applies before the first paint.

// The theme the visitor picked on another OpenMob page (the "openmob.theme" setting), if any.
try {
  const theme = localStorage.getItem("openmob.theme");
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
} catch {}

// Already signed in (another tab, or a back button): go to the dashboard, or to ?next= when it's on this site.
fetch("/api/auth/me", { credentials: "same-origin" })
  .then((r) => r.json())
  .then((me) => {
    if (!me || !me.email) return;
    const target = new URL(new URLSearchParams(location.search).get("next") || "/", location.origin);
    // Same origin, and not a path the browser reads as another host ("/.//evil.example" resolves to "//evil.example").
    const same = target.origin === location.origin && !/^\/[\/\\]/.test(target.pathname);
    location.replace(same ? target.pathname + target.search + target.hash : "/");
  })
  .catch(() => {});
