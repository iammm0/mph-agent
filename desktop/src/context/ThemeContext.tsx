import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from "react";

const STORAGE_KEY = "mph-agent-theme-v3";
const LEGACY_STORAGE_KEYS = ["mph-agent-theme-v2", "comsol-agent-theme"];

export type ThemeMode = "light" | "dark" | "system";

/** 解析后的实际主题（用于 data-theme） */
export type ResolvedTheme = "light" | "dark";

export function getSystemTheme(): ResolvedTheme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** 与 https://www.mphagent.site/ 品牌色对齐 */
export const BRAND_ACCENT = "#00bffa";
export const BRAND_NAVY = "#002b70";

export const ACCENT_PRESETS: { name: string; value: string }[] = [
  { name: "品牌青", value: BRAND_ACCENT },
  { name: "深蓝", value: BRAND_NAVY },
  { name: "天蓝", value: "#4f8cff" },
  { name: "青碧", value: "#0891b2" },
  { name: "苔绿", value: "#059669" },
  { name: "琥珀", value: "#d97706" },
  { name: "陶土", value: "#d97757" },
];

export interface ThemeState {
  themeMode: ThemeMode;
  accentColor: string;
}

interface ThemeContextValue extends ThemeState {
  setThemeMode: (mode: ThemeMode) => void;
  setAccentColor: (color: string) => void;
}

const defaultState: ThemeState = {
  themeMode: "light",
  accentColor: BRAND_ACCENT,
};

/** 旧主题残留强调色 → 迁到官网品牌青 */
const LEGACY_NON_BRAND_ACCENTS = new Set(
  [
    "#d97757",
    "#dcc88a",
    "#c89a4a",
    "#9ec48c",
    "#e8d49a",
    "#c97a5e",
    "#5a8c6a",
    "#2563eb",
    "#7c3aed",
    "#0891b2",
    "#059669",
    "#ea580c",
    "#dc2626",
    "#2f4a6f",
    "#1e3a5f",
  ].map((s) => s.toLowerCase())
);

function normalizeAccent(raw: string | undefined): string {
  if (typeof raw === "string" && /^#[0-9A-Fa-f]{6}$/.test(raw)) {
    if (LEGACY_NON_BRAND_ACCENTS.has(raw.toLowerCase())) return BRAND_ACCENT;
    return raw;
  }
  return defaultState.accentColor;
}

function loadTheme(): ThemeState {
  try {
    let raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      for (const key of LEGACY_STORAGE_KEYS) {
        raw = localStorage.getItem(key);
        if (raw) {
          localStorage.setItem(STORAGE_KEY, raw);
          localStorage.removeItem(key);
          break;
        }
      }
    }
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<ThemeState>;
      const mode = parsed.themeMode;
      return {
        themeMode:
          mode === "dark" || mode === "system" || mode === "light"
            ? mode
            : defaultState.themeMode,
        accentColor: normalizeAccent(parsed.accentColor),
      };
    }
  } catch {
    // ignore
  }
  return defaultState;
}

function hexToRgb(hex: string): string {
  const h = hex.replace("#", "");
  if (h.length !== 6) return "0, 191, 250";
  const n = parseInt(h, 16);
  return `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
}

function applyAccent(accent: string) {
  const root = document.documentElement;
  root.style.setProperty("--accent", accent);
  root.style.setProperty("--accent-rgb", hexToRgb(accent));
  root.style.setProperty("--primary", accent);
  root.style.setProperty("--primary-rgb", hexToRgb(accent));
  root.style.setProperty("--border-active", accent);
}

export function initTheme(): void {
  const state = loadTheme();
  const root = document.documentElement;
  const resolved =
    state.themeMode === "system" ? getSystemTheme() : state.themeMode;
  root.setAttribute("data-theme", resolved);
  applyAccent(state.accentColor);
}

function saveTheme(state: ThemeState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // ignore
  }
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ThemeState>(loadTheme);

  const setThemeMode = useCallback((themeMode: ThemeMode) => {
    setState((prev) => {
      const next = { ...prev, themeMode };
      saveTheme(next);
      return next;
    });
  }, []);

  const setAccentColor = useCallback((accentColor: string) => {
    setState((prev) => {
      const next = { ...prev, accentColor };
      saveTheme(next);
      return next;
    });
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    const resolved: ResolvedTheme =
      state.themeMode === "system" ? getSystemTheme() : state.themeMode;
    root.setAttribute("data-theme", resolved);
    applyAccent(state.accentColor);
  }, [state.themeMode, state.accentColor]);

  useEffect(() => {
    if (state.themeMode !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
      const resolved = media.matches ? "dark" : "light";
      document.documentElement.setAttribute("data-theme", resolved);
    };
    media.addEventListener("change", handler);
    return () => media.removeEventListener("change", handler);
  }, [state.themeMode]);

  const value: ThemeContextValue = {
    ...state,
    setThemeMode,
    setAccentColor,
  };

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx)
    throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
