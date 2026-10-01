(function () {
  const SERVER_URL = "https://gostingmusicium.bothost.tech";
  if (typeof window !== "undefined" && window.location) {
    if (window.location.origin && window.location.origin.includes("discordsays.com")) {
      window.MUSICBOT_API = SERVER_URL;
    } else {
      window.MUSICBOT_API = window.location.origin;
    }
  }
})();
