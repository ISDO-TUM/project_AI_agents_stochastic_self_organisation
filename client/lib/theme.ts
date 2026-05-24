export const BURG = "#8B1A2F";
export const BURG_LT = "#C4374F";
export const BURG_DIM = "rgba(139,26,47,0.13)";
export const BURG_GLOW = "rgba(139,26,47,0.3)";

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
    return {
      bg: "#060608",
      pill: "rgba(10,8,18,0.84)",
      pillBorder: "rgba(139,26,47,0.18)",
      surface: "rgba(12,10,20,0.96)",
      border: "rgba(255,255,255,0.07)",
      borderHi: "rgba(255,255,255,0.12)",
      text: "#eceaf5",
      textSub: "#9694b0",
      textDim: "#5c5a78",
      inputBg: "rgba(0,0,0,0.38)",
      hover: "rgba(255,255,255,0.04)",
      dotColor: "rgba(255,255,255,0.07)",
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
