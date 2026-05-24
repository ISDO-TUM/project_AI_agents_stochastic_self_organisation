import { ThemeProvider } from "@/lib/theme-context";
import { ApiKeysProvider } from "@/lib/api-keys-context";
import { App } from "@/components/app";

export default function Home() {
  return (
    <ThemeProvider>
      <ApiKeysProvider>
        <App />
      </ApiKeysProvider>
    </ThemeProvider>
  );
}
