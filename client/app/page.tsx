import { ThemeProvider } from "@/lib/theme-context";
import { ApiKeysProvider } from "@/lib/api-keys-context";
import { AppShell } from "@/components/app-shell";

export default function Home() {
  return (
    <ThemeProvider>
      <ApiKeysProvider>
        <AppShell />
      </ApiKeysProvider>
    </ThemeProvider>
  );
}
