// Sidebar navigation — order and labels come straight from the product spec.
import {
  LayoutDashboard,
  Search,
  Sparkles,
  FileText,
  UserCircle,
  Wand2,
  ListChecks,
  Workflow,
  Activity,
  Cloud,
  Settings as SettingsIcon,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  label: string;
  href: string;
  icon: LucideIcon;
};

export const NAV_ITEMS: NavItem[] = [
  { label: "Overview", href: "/", icon: LayoutDashboard },
  { label: "AI Job Search", href: "/search", icon: Search },
  { label: "Recommended Jobs", href: "/matches", icon: Sparkles },
  { label: "Resume Manager", href: "/resume", icon: FileText },
  { label: "Candidate Profile", href: "/profile", icon: UserCircle },
  { label: "Application Assistant", href: "/assistant", icon: Wand2 },
  { label: "Application Tracker", href: "/tracker", icon: ListChecks },
  { label: "Automation Center", href: "/automation", icon: Workflow },
  { label: "AI Agent Activity", href: "/agents", icon: Activity },
  { label: "AWS Infrastructure", href: "/infrastructure", icon: Cloud },
  { label: "Settings", href: "/settings", icon: SettingsIcon },
];
