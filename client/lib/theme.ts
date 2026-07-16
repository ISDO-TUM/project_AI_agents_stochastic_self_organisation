export const BURG = "#8B1A2F";
export const BURG_LT = "#C4374F";
export const BURG_DIM = "rgba(139,26,47,0.13)";
export const BURG_GLOW = "rgba(139,26,47,0.3)";

/** Base RGB for the dark-mode glass panel scrim (boards, activity log, modals),
 *  lit a few points above the canvas so content panels read as elevated layers
 *  rather than near-black holes. Callers set their own alpha:
 *  `rgba(${SURFACE_DARK_RGB},0.94)`. Light-mode analogue is `248,246,255`. */
export const SURFACE_DARK_RGB = "35,31,49";
export const SURFACE_LIGHT_RGB = "248,246,255";
/** Deep frame/veil behind everything (body, full-screen modal backdrops). */
export const FRAME_DARK = "#0d0c13";

interface ThemeTokens {
  bg: string;
  pill: string;
  pillBorder: string;
  surface: string;
  border: string;
  borderHi: string;
  text: string;
  textSub: string;
  textDim: string;
  inputBg: string;
  hover: string;
  dotColor: string;
}

export function getTheme(dark: boolean): ThemeTokens {
  if (dark) {
    // Elevation ladder mirrors light mode: the canvas is a comfortable dark
    // plane (not near-black) and every surface sits *above* it, a few lightness
    // points brighter, so cards/boards read as distinct layers instead of
    // dissolving into a black void. See SURFACE_DARK for the matching scrim used
    // by translucent glass panels (boards, activity log, modals).
    return {
      bg: "#16141e",
      pill: "rgba(35,31,49,0.92)",
      pillBorder: "rgba(139,26,47,0.34)",
      surface: "rgba(42,37,58,0.97)",
      border: "rgba(255,255,255,0.14)",
      borderHi: "rgba(255,255,255,0.26)",
      text: "#eceaf5",
      textSub: "#a6a3bf",
      textDim: "#7a779c",
      inputBg: "rgba(0,0,0,0.22)",
      hover: "rgba(255,255,255,0.07)",
      dotColor: "rgba(255,255,255,0.12)",
    };
  }
  return {
    bg: "#f0eef8",
    pill: "rgba(255,255,255,0.86)",
    pillBorder: "rgba(139,26,47,0.14)",
    surface: "rgba(255,255,255,0.98)",
    border: "rgba(0,0,0,0.08)",
    borderHi: "rgba(0,0,0,0.14)",
    text: "#18161f",
    textSub: "#3a3848",
    textDim: "#4e4c68",
    inputBg: "rgba(0,0,0,0.04)",
    hover: "rgba(0,0,0,0.04)",
    dotColor: "rgba(0,0,0,0.1)",
  };
}
