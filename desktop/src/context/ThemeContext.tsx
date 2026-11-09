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

/** 与 https://www.mphagent.site/ 品牌色对齐；强调色仅保留品牌青 */
export const BRAND_ACCENT = "#00bffa";
export const BRAND_NAVY = "#002b70";
export const BRAND_ACCENT_RGB = "0, 191, 250";

export interface ThemeState {
  themeMode: ThemeMode;
}

interface ThemeContextValue extends ThemeState {
  accentColor: typeof BRAND_ACCENT;
  setThemeMode: (mode: ThemeMode) => void;
}

const defaultState: ThemeState = {
  themeMode: "light",
};

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
      const parsed = JSON.parse(raw) as Partial<ThemeState> & {
        accentColor?: string;
      };
      const mode = parsed.themeMode;
      return {
        themeMode:
          mode === "dark" || mode === "system" || mode === "light"
            ? mode
            : defaultState.themeMode,
      };
    }
  } catch {
    // ignore
  }
  return defaultState;
}

function applyBrandAccent() {
  const root = document.documentElement;
  root.style.setProperty("--accent", BRAND_ACCENT);
  root.style.setProperty("--accent-rgb", BRAND_ACCENT_RGB);
  root.style.setProperty("--primary", BRAND_ACCENT);
  root.style.setProperty("--primary-rgb", BRAND_ACCENT_RGB);
  root.style.setProperty("--border-active", BRAND_ACCENT);
}

export function initTheme(): void {
  const state = loadTheme();
  const root = document.documentElement;
  const resolved =
    state.themeMode === "system" ? getSystemTheme() : state.themeMode;
  root.setAttribute("data-theme", resolved);
  applyBrandAccent();
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

  useEffect(() => {
    const root = document.documentElement;
    const resolved: ResolvedTheme =
      state.themeMode === "system" ? getSystemTheme() : state.themeMode;
    root.setAttribute("data-theme", resolved);
    applyBrandAccent();
  }, [state.themeMode]);

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
    accentColor: BRAND_ACCENT,
    setThemeMode,
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
