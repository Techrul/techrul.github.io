# Working on this repo

- **Test on `dev` first.** Changes go to the `dev` branch, get a test build (`gh workflow run update.yml --ref dev`)
  and a look at the preview site, and only then reach `main` (which deploys techrul.github.io). Don't push to `main`
  directly.
- Runs on any branch other than `main` build everything but don't deploy or commit data. A run on `dev` also
  publishes its build at https://techrul.github.io/preview/ (see `.github/workflows/preview.yml`): it uploads the
  build to the `preview` release and starts preview.yml on main, which deploys the live site plus `/preview/`.
- Liquipedia allows 60 requests an hour; one update uses up to 30, so back-to-back test runs can hit the limit.
