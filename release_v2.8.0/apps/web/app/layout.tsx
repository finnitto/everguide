import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Everguide | Find funeral care with confidence",
  description: "A clear, helpful directory of funeral service providers."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en-GB"><body>{children}</body></html>;
}
