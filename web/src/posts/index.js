// Blog posts. Body markdown lives in sibling .md files, imported raw (Vite ?raw).
// Metadata (title/description/date/tag) is kept here so it stays consistent and
// SEO-controlled; the .md files are pure prose with no frontmatter or H1.
import buildingInPublic from "./building-koyracloud-in-public.md?raw";
import deployFastapiReact from "./deploy-fastapi-react-homelab.md?raw";
import noKubernetes from "./you-dont-need-kubernetes.md?raw";
import migratingOffVercel from "./migrating-off-vercel.md?raw";
import selfHostedPaas from "./self-hosted-paas-docker-swarm.md?raw";
import vercelAlt from "./open-source-vercel-alternative.md?raw";
import herokuAlt from "./self-hosted-heroku-alternative.md?raw";
import pushToDeploy from "./push-to-deploy-git.md?raw";
import workersCron from "./background-workers-and-cron.md?raw";
import customDomains from "./custom-domains-automatic-https.md?raw";
import appsIntoImages from "./apps-into-images-not-nfs.md?raw";
import homelabPaas from "./homelab-paas.md?raw";

export const POSTS = [
  {
    slug: "building-koyracloud-in-public",
    title: "I built my own Vercel in a month — here's the architecture",
    description:
      "Building a self-hosted PaaS solo: the two-half control-plane/pipeline architecture, the NFS design I got wrong first, and every feature I said no to on purpose.",
    date: "2026-06-30",
    tag: "Build log",
    body: buildingInPublic,
  },
  {
    slug: "deploy-fastapi-react-homelab",
    title: "Deploy a FastAPI + React app to your homelab",
    description:
      "A concrete walkthrough: the .paas/app.yaml manifest for a full-stack Python+Node app, build vs predeploy, build-time env traps, push-to-deploy, and adding a worker later.",
    date: "2026-06-28",
    tag: "Tutorial",
    body: deployFastapiReact,
  },
  {
    slug: "you-dont-need-kubernetes",
    title: "You don't need Kubernetes to self-host your apps",
    description:
      "The push-a-repo-get-a-URL loop most people want doesn't require Kubernetes. Why Docker Swarm plus a thin PaaS layer is the right amount of machinery for a homelab.",
    date: "2026-06-26",
    tag: "Opinion",
    body: noKubernetes,
  },
  {
    slug: "migrating-off-vercel",
    title: "Migrating a Next.js app off Vercel, the honest version",
    description:
      "The two genuinely fiddly parts of moving Next.js to your own hardware — the Dockerfile and the apex domain — plus the build-env, pnpm, and email traps that bite everyone.",
    date: "2026-06-25",
    tag: "Guide",
    body: migratingOffVercel,
  },
  {
    slug: "self-hosted-paas-docker-swarm",
    title: "Self-hosting a PaaS on your Docker Swarm",
    description:
      "What a self-hosted PaaS actually is, why Docker Swarm is a sane base for one, and what you get over hand-rolling compose, Traefik and a registry yourself.",
    date: "2026-06-24",
    tag: "Guide",
    body: selfHostedPaas,
  },
  {
    slug: "open-source-vercel-alternative",
    title: "An open-source Vercel alternative for your own hardware",
    description:
      "Vercel's developer experience is genuinely good. Here's what you keep and what you give up when you self-host that git-push-to-URL loop on your own metal.",
    date: "2026-06-20",
    tag: "Comparison",
    body: vercelAlt,
  },
  {
    slug: "self-hosted-heroku-alternative",
    title: "The self-hosted version of the Heroku workflow",
    description:
      "Procfiles, dynos, config vars, Scheduler and the Redis add-on — mapped onto a self-hosted PaaS you run on your own Docker Swarm.",
    date: "2026-06-17",
    tag: "Comparison",
    body: herokuAlt,
  },
  {
    slug: "push-to-deploy-git",
    title: "Push-to-deploy, without the CI yak-shave",
    description:
      "Connect a repo once, push, and it builds an image and ships it — or deploys only after your CI goes green. How the pipeline works, with live logs and rollback.",
    date: "2026-06-13",
    tag: "Feature",
    body: pushToDeploy,
  },
  {
    slug: "background-workers-and-cron",
    title: "Background workers and cron from the same repo",
    description:
      "Declare always-on workers, scheduled jobs and a per-app Redis bus in one manifest, off one image — with run history, a Run-now button and no catch-up storms.",
    date: "2026-06-11",
    tag: "Feature",
    body: workersCron,
  },
  {
    slug: "custom-domains-automatic-https",
    title: "Custom domains and automatic HTTPS, the boring way",
    description:
      "Point a record, a certificate appears, it renews itself, you forget about it. Platform subdomains via Traefik and custom domains via Cloudflare for SaaS.",
    date: "2026-06-09",
    tag: "Feature",
    body: customDomains,
  },
  {
    slug: "apps-into-images-not-nfs",
    title: "Why we build each app into its own image, off NFS",
    description:
      "We tried serving app code over NFS. It bit us. Here's the rewrite to per-app container images and an internal registry — and why it removed more code than it added.",
    date: "2026-06-06",
    tag: "Engineering",
    body: appsIntoImages,
  },
  {
    slug: "homelab-paas",
    title: "A homelab that pays rent",
    description:
      "Most homelab hardware sits mostly idle. Closing the gap between 'I have servers' and 'I can ship to them like a small cloud' — so a new idea costs almost no friction.",
    date: "2026-06-03",
    tag: "Essay",
    body: homelabPaas,
  },
];

export const getPost = (slug) => POSTS.find((p) => p.slug === slug);

// ponytail: ~200 wpm word-count estimate; good enough for a "5 min read" label.
export const readingTime = (body) =>
  Math.max(1, Math.round(body.trim().split(/\s+/).length / 200));
