import type { MetadataRoute } from "next";
import { APP_NAME } from "@/lib/constants";
import { getTournament } from "@/lib/tournament";

export default async function manifest(): Promise<MetadataRoute.Manifest> {
  const tournament = await getTournament();
  return {
    id: "/",
    name: `${APP_NAME} — ${tournament.name} Predictions`,
    short_name: APP_NAME,
    description: `Explainable predictions for the ${tournament.name} from FinalWhistle's in-house ML model — win probabilities, scorelines, group & knockout odds. For analytics and entertainment only.`,
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#0d1118",
    theme_color: "#0d1118",
    categories: ["sports", "entertainment"],
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      // Distinct maskable assets: logo confined to the ~80% safe zone on the
      // brand background, so Android circle/squircle masks never clip it.
      { src: "/icon-maskable-192.png", sizes: "192x192", type: "image/png", purpose: "maskable" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
