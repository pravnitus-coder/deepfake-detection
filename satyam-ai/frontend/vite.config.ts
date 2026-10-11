import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

function inlineStandaloneAssets(): Plugin {
  return {
    name: "inline-standalone-assets",
    apply: "build",
    enforce: "post",
    generateBundle(_options, bundle) {
      const html = bundle["index.html"];
      if (!html || html.type !== "asset") {
        throw new Error("Could not create standalone HTML: index.html was not emitted.");
      }

      let source = typeof html.source === "string" ? html.source : new TextDecoder().decode(html.source);
      let inlinedScript = false;
      source = source.replace(
        /<script\b([^>]*?)\s+src=["']([^"']+)["']([^>]*)>\s*<\/script>/g,
        (_tag, before: string, assetPath: string, after: string) => {
          const fileName = assetPath.replace(/^\.?\//, "");
          const chunk = bundle[fileName];
          if (!chunk || chunk.type !== "chunk") {
            throw new Error(`Could not inline JavaScript asset: ${assetPath}`);
          }

          inlinedScript = true;
          const attributes = `${before}${after}`.replace(/\s+crossorigin(?:=["'][^"']*["'])?/i, "");
          return `<script${attributes}>${chunk.code}</script>`;
        },
      );
      if (!inlinedScript) {
        throw new Error("Could not create standalone HTML: no JavaScript entry was found.");
      }

      source = source.replace(
        /<link\b(?=[^>]*\brel=["']stylesheet["'])[^>]*\bhref=["']([^"']+\.css)["'][^>]*>/g,
        (_tag, assetPath: string) => {
          const fileName = assetPath.replace(/^\.?\//, "");
          const asset = bundle[fileName];
          if (!asset || asset.type !== "asset") {
            throw new Error(`Could not inline CSS asset: ${assetPath}`);
          }

          const css = typeof asset.source === "string" ? asset.source : new TextDecoder().decode(asset.source);
          return `<style>${css}</style>`;
        },
      );
      html.source = source;
    },
  };
}

export default defineConfig({
  base: "./",
  plugins: [react(), inlineStandaloneAssets()],
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
  preview: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
});
