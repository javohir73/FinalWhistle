import type { MetadataRoute } from "next";

const SITE = "https://fifa-wc26-prediction.vercel.app";

export default function sitemap(): MetadataRoute.Sitemap {
  const daily = ["", "/matches", "/groups", "/brackets"];
  const evergreen = ["/about", "/methodology"];
  return [
    ...daily.map((path) => ({
      url: `${SITE}${path}`,
      changeFrequency: "daily" as const,
      priority: path === "" ? 1 : 0.7,
    })),
    ...evergreen.map((path) => ({
      url: `${SITE}${path}`,
      changeFrequency: "monthly" as const,
      priority: 0.5,
    })),
  ];
}
