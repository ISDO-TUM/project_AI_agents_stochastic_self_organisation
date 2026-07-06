import { AgentsPage } from "@/components/agents-page";
import { ThemeProvider } from "@/lib/theme-context";

export default function AgentsRoute() {
  return (
    <ThemeProvider>
      <AgentsPage />
    </ThemeProvider>
  );
}
