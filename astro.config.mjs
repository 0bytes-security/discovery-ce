import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import starlightLinksValidator from "starlight-links-validator";
import tailwind from "@astrojs/tailwind";
import starlightOpenAPI, { openAPISidebarGroups } from "starlight-openapi";

export default defineConfig({
  site: "https://discovery.0bytes.io",
  integrations: [
    starlight({
      title: "Discovery",
      description: "Security Assessments Made Simple",
      components: {
        Header: "~/components/header.astro",
        Hero: "~/components/hero.astro",
        PageFrame: "~/components/page-frame.astro",
        TableOfContents: "~/components/table-of-contents.astro",
      },
      customCss: ["~/styles/tailwind.css"],
      plugins: [
        starlightLinksValidator({}),
        starlightOpenAPI([
          {
            base: "api/references",
            label: "API References",
            schema: "src/openapi.json",
          },
        ]),
      ],
      sidebar: [
        {
          label: "Overview",
          link: "/overview",
        },
        {
          label: "Architecture",
          link: "/architecture",
        },
        ...openAPISidebarGroups,
      ],
      social: {
        github: "https://github.com/0bytes-security/discovery-ce",
      },
    }),
    tailwind({
      applyBaseStyles: false,
    }),
  ],
  server: {
    port: 1104,
  },
});
