import type { MetadataRoute } from "next";

const SITE = "https://fifa-wc26-prediction.vercel.app";

export default function sitemap(): MetadataRoute.Sitemap {
  const routes = ["", "/matches", "/groups", "/brackets", "/about"];
  return routes.map((path) => ({
    url: `${SITE}${path}`,
    changeFrequency: path === "/about" ? "monthly" : "daily",
    priority: path === "" ? 1 : 0.7,
  }));
}
