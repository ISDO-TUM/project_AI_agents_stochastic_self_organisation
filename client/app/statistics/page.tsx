import { StatisticsDashboard } from "@/components/statistics/dashboard";
import { ApiKeysProvider } from "@/lib/api-keys-context";
import { ThemeProvider } from "@/lib/theme-context";

export default function StatisticsRoute() {
  return (
    <ThemeProvider>
      <ApiKeysProvider>
        <StatisticsDashboard />
      </ApiKeysProvider>
    </ThemeProvider>
  );
}
