import { cpSync, existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const desktopRoot = path.dirname(fileURLToPath(import.meta.url));

function syncIconsaxPublic() {
  const src = path.join(desktopRoot, "node_modules/iconsax/dist");
  const dest = path.join(desktopRoot, "public/iconsax");
  if (!existsSync(src)) return;
  mkdirSync(path.dirname(dest), { recursive: true });
  cpSync(src, dest, { recursive: true });
}

syncIconsaxPublic();

const host = process.env.TAURI_DEV_HOST;

/**
 * 固定拆出 React / Tauri / Markdown / MathJax，其余交给 Rollup 默认分包，
 * 避免出现 vendor ↔ markdown 的 circular chunk。
 */
function manualChunks(id: string): string | undefined {
  if (!id.includes("node_modules")) return;
  const norm = id.replace(/\\/g, "/");
  if (norm.includes("/better-react-mathjax/") || norm.includes("/mathjax")) {
    return "mathjax";
  }
  if (
    norm.includes("/react-markdown/") ||
    norm.includes("/remark-") ||
    norm.includes("/rehype-")
  ) {
    return "markdown";
  }
  if (/\/node_modules\/react\//.test(norm) || /\/node_modules\/react-dom\//.test(norm)) {
    return "react-core";
  }
  if (/\/node_modules\/scheduler\//.test(norm)) {
    return "react-core";
  }
  if (norm.includes("/@tauri-apps/")) {
    return "tauri";
  }
  return undefined;
}

export default defineConfig(async () => ({
  plugins: [react()],
  clearScreen: false,
  build: {
    /** MathJax 压缩后仍常 >500kB，属预期；桌面端单包可接受 */
    chunkSizeWarningLimit: 2000,
    rollupOptions: {
      output: {
        manualChunks,
      },
    },
  },
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
}));
