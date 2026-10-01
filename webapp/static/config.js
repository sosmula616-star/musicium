(function () {
  let apiBase = "";
  if (typeof window !== "undefined" && window.location) {
    const origin = window.location.origin || "";
    if (origin.includes("discordsays.com")) {
      // Inside Discord Embedded App Activity, all requests must go via /.proxy
      apiBase = "/.proxy";
    } else if (window.location.protocol === "file:") {
      apiBase = "https://gostingmusicium.bothost.tech";
    } else {
      // Standalone web browser on server domain
      apiBase = "";
    }
  }
  window.MUSICBOT_API = apiBase;
})();
