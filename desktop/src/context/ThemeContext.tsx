import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from "react";

const STORAGE_KEY = "mph-agent-theme";
const LEGACY_STORAGE_KEY = "comsol-agent-theme";

export type ThemeMode = "light" | "dark" | "system";

/** 解析后的实际主题（用于 data-theme） */
export type ResolvedTheme = "light" | "dark";

export function getSystemTheme(): ResolvedTheme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export const ACCENT_PRESETS: { name: string; value: string }[] = [
  { name: "蓝", value: "#2563eb" },
  { name: "紫", value: "#7c3aed" },
  { name: "青", value: "#0891b2" },
  { name: "绿", value: "#059669" },
  { name: "橙", value: "#ea580c" },
  { name: "红", value: "#dc2626" },
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
  themeMode: "system",
  accentColor: ACCENT_PRESETS[0].value,
};

function loadTheme(): ThemeState {
  try {
    let raw = localStorage.getItem(STORAGE_KEY);
    if (!raw && LEGACY_STORAGE_KEY) {
      raw = localStorage.getItem(LEGACY_STORAGE_KEY);
      if (raw) {
        localStorage.setItem(STORAGE_KEY, raw);
        localStorage.removeItem(LEGACY_STORAGE_KEY);
      }
    }
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<ThemeState>;
      const mode = parsed.themeMode;
      return {
        themeMode:
          mode === "dark" || mode === "system" ? mode : "light",
        accentColor:
          typeof parsed.accentColor === "string" &&
          /^#[0-9A-Fa-f]{6}$/.test(parsed.accentColor)
            ? parsed.accentColor
            : defaultState.accentColor,
      };
    }
  } catch {
    // ignore
  }
  return defaultState;
}

export function initTheme(): void {
  const state = loadTheme();
  const root = document.documentElement;
  const resolved =
    state.themeMode === "system" ? getSystemTheme() : state.themeMode;
  root.setAttribute("data-theme", resolved);
  root.style.setProperty("--accent", state.accentColor);
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
    root.style.setProperty("--accent", state.accentColor);
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
