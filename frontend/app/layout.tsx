import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Le métier que ta philosophie t'aurait choisi",
  description:
    "Treize questions inspirées des grands philosophes pour découvrir ton trait dominant et le métier qui lui ressemble.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Spectral:ital,wght@0,300;0,400;0,600;1,300;1,400&display=swap"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
