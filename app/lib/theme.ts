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
      bg: "#0c0b14",
      pill: "rgba(14,12,24,0.88)",
      pillBorder: "rgba(139,26,47,0.28)",
      surface: "rgba(18,16,30,0.97)",
      border: "rgba(255,255,255,0.13)",
      borderHi: "rgba(255,255,255,0.24)",
      text: "#eceaf5",
      textSub: "#9694b0",
      textDim: "#6a688a",
      inputBg: "rgba(0,0,0,0.3)",
      hover: "rgba(255,255,255,0.06)",
      dotColor: "rgba(255,255,255,0.11)",
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
