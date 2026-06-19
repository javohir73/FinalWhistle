import type { CapacitorConfig } from "@capacitor/cli";

/** FinalWhistle native shell (App Store / Play Store).
 *
 *  Remote-shell mode (decision in docs/NATIVE-SHELL.md): the webview loads the
 *  deployed Vercel origin, so it shares the PWA's first-party origin — the
 *  fw_session cookie, /backend-api proxy, service worker and offline page all
 *  behave exactly like the installed PWA. No separate native auth transport. */
const config: CapacitorConfig = {
  appId: "com.finalwhistle.app",
  appName: "FinalWhistle",
  webDir: "public", // required by the CLI; unused while server.url is set
  server: {
    url: "https://fifa-wc26-prediction.vercel.app",
    allowNavigation: ["fifa-wc26-prediction.vercel.app"],
  },
  ios: {
    contentInset: "automatic",
    // Daylight theme background — matches the web --background token so there's
    // no dark flash on launch or behind the safe-area insets / overscroll.
    backgroundColor: "#f6f8f3",
  },
  android: {
    backgroundColor: "#f6f8f3",
  },
};

export default config;
