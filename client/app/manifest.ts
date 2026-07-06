import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Mycellium",
    short_name: "Mycellium",
    description: "Drop a new agent in. It finds its place. The system adapts.",
    start_url: "/",
    display: "standalone",
    background_color: "#060608",
    theme_color: "#8b1a2f",
    icons: [
      {
        src: "/icon.png",
        sizes: "512x512",
        type: "image/png",
      },
    ],
  };
}
