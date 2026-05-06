import { ThemeProvider } from "@/lib/theme-context";
import { App } from "@/components/app";

export default function Home() {
  return (
    <ThemeProvider>
      <App />
    </ThemeProvider>
  );
}
