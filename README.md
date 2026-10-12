# Web App → Docker → Helm → Kubernetes → Argo CD (on OrbStack)

A step-by-step learning project in three parts:

| Part | What you do | Result |
|---|---|---|
| **1** | Build a Flask web app and deploy it with Helm, with the **web app and database as two containers in one pod** | `READY 2/2` pod |
| **2** | Install **Argo CD** and let it deploy from Git (GitOps) | Push to Git, and it deploys itself |
| **3** | On a **Git branch with a Pull Request**: **move the database into its own pod** (StatefulSet), scale the web tier, and **add an image under the table** | Production-style layout and team workflow |

The app shows an image and a table you can add, edit and delete rows in. The table has 6 fields: name, email, role, department, location and start date.

```
PART 1 – one pod, two containers                PART 3 – separate pods

┌────────── Pod: simple-webapp ──────────┐      Service: simple-webapp (port 80)
│ ┌─────────────┐ 127.0.0.1 ┌──────────┐ │          ┌─────────┴─────────┐
│ │ web (Flask) │──────────▶│ db (PG16)│ │      ┌───▼────┐        ┌────▼───┐
│ │ :8000       │   :5432   │ :5432    │ │      │ web #1 │        │ web #2 │  ← Deployment
│ └─────────────┘           └────┬─────┘ │      └───┬────┘        └────┬───┘
└────────────────────────────────┼───────┘          └────────┬─────────┘
                                 │                           │ simple-webapp-db:5432
             PVC: simple-webapp-db-data                ┌─────▼──────────────┐
                                                       │ simple-webapp-db-0 │  ← StatefulSet
                                                       └─────┬──────────────┘
                                                PVC: data-simple-webapp-db-0
```

**Names used throughout this guide**

| Thing | Value |
|---|---|
| Helm release / Argo CD app | `simple-webapp` |
| Namespace | `webapp` |
| Web Service | `simple-webapp` (port 80 → pod port 8000) |
| Database (Part 3) | Service `simple-webapp-db`, pod `simple-webapp-db-0` (port 5432) |
| Images | `webapp:1.0.0` (Parts 1–2), `webapp:1.1.0` (Part 3) |

> **Rule to remember:** every Kubernetes name (namespaces, apps, releases) must be **lowercase**: letters, numbers and `-` only. `WebApp` fails; `webapp` works.

---

## Contents

**Part 1 – Build and deploy (single pod)**
[1. Prerequisites](#step-1--prerequisites) · [2. Understand the project](#step-2--understand-the-project) · [3. Run locally with Docker Compose](#step-3--run-it-locally-with-docker-compose) · [4. Build the image](#step-4--build-the-image-for-kubernetes) · [5. Explore the Helm chart](#step-5--explore-and-check-the-helm-chart) · [6. Install with Helm](#step-6--install-with-helm-and-explore)

**Part 2 – Argo CD and GitOps**
[7. Push to GitHub](#step-7--push-the-project-to-github) · [8. Install and open Argo CD](#step-8--install-and-open-argo-cd) · [9. Create the Application](#step-9--create-the-argo-cd-application) · [10. The GitOps loop](#step-10--the-gitops-loop)

**Part 3 – Move the DB to its own pod + add an image**
[11. Why](#step-11--why-separate-pods) · [12. What changes](#step-12--what-changes) · [13. Tag + branch](#step-13--bookmark-part-2-and-create-a-branch) · [14. Back up](#step-14--back-up-your-table-data) · [15. Swap in the new chart](#step-15--swap-in-the-part-3-chart) · [16. Build 1.1.0](#step-16--build-the-new-image-version) · [17. Check](#step-17--check-the-chart) · [18. Push branch + open PR](#step-18--commit-push-the-branch-and-open-a-pull-request) · [19. Merge and watch](#step-19--merge-and-watch-argo-cd-roll-it-out) · [20. Restore](#step-20--restore-your-data) · [21. Explore](#step-21--explore-the-new-layout) · [22. More GitOps practice](#step-22--more-gitops-practice-with-branches)

**Reference**
[Troubleshooting](#troubleshooting) · [Command cheat sheet](#command-cheat-sheet) · [Clean up](#clean-up) · [Learning notes](#learning-notes)

---

# Part 1 – Build and deploy (single pod)

## Step 1 – Prerequisites

1. **Enable Kubernetes in OrbStack**: OrbStack → Settings → Kubernetes → *Enable Kubernetes*. Wait until it shows as running.
2. Install the tools:

   ```bash
   brew install kubectl helm git argocd
   ```

3. Check everything works:

   ```bash
   docker version
   kubectl config use-context orbstack
   kubectl get nodes          # 1 node, STATUS Ready
   helm version
   ```

4. A **GitHub account**. Argo CD pulls your chart from Git in Part 2.

---

## Step 2 – Understand the project

```
webapp/
├── app/                          # the web application (same code for all parts)
│   ├── app.py                    # Flask routes + database code
│   ├── templates/                # index.html (table), edit.html
│   ├── static/                   # logo.svg (header), team.svg (used in Part 3), style.css
│   ├── requirements.txt
│   └── Dockerfile
├── compose.yaml                  # run locally with Docker before Kubernetes
├── helm/webapp/                  # THE chart Argo CD deploys (starts as the Part 1 version)
│   ├── Chart.yaml
│   ├── values.yaml               # settings you change
│   └── templates/
│       ├── deployment.yaml       # ONE pod with TWO containers: web + db
│       ├── pvc.yaml              # volume for the database
│       ├── secret.yaml           # DB name / user / password
│       ├── service.yaml          # web Service (port 80)
│       ├── _helpers.tpl          # shared names and labels
│       └── NOTES.txt             # message printed after install
├── part3/helm-webapp/            # the Part 3 chart (DB in its own pod), copied over in Step 15
└── argocd/application.yaml       # tells Argo CD where your chart lives
```

Key ideas in `app/app.py`:

- All config comes from **environment variables** (`DB_HOST`, `DB_PASSWORD`, `APP_TITLE`, `BANNER_IMAGE`). Helm sets these.
- The app doesn't care where the database is; it only uses `DB_HOST`. In Part 1 that's `127.0.0.1` (same pod). In Part 3 it's the Service name `simple-webapp-db`.
- `init_db()` waits for Postgres, then creates the `people` table if it's missing.
- Routes: `/` (table + add form), `/add`, `/edit/<id>`, `/delete/<id>`.
- `/healthz` (liveness) and `/ready` (readiness, which also checks the DB) are for Kubernetes probes.
- The page footer shows **which pod served it**, which becomes useful in Part 3.

---

## Step 3 – Run it locally with Docker Compose

This checks the app works before Kubernetes is involved.

```bash
cd webapp
docker compose up --build
```

Open <http://localhost:8000>. Add a few rows, edit one and delete one.

Stop with `Ctrl+C`, then clean up:

```bash
docker compose down -v      # -v also deletes the local test database
```

---

## Step 4 – Build the image for Kubernetes

```bash
docker build -t webapp:1.0.0 ./app
docker images | grep webapp
```

> **No registry needed.** OrbStack's Kubernetes shares the Docker engine on your Mac, so the cluster can use this local image directly.
>
> **Why not `:latest`?** Kubernetes treats `latest` as "always pull from a registry", which fails for a local-only image. A real tag plus `imagePullPolicy: IfNotPresent` uses the local copy.

---

## Step 5 – Explore and check the Helm chart

- `values.yaml` holds the settings. Templates read them as `{{ .Values.something }}`.
- `deployment.yaml` defines **one pod with two containers**, `web` and `db`. Containers in a pod share a network, so the app connects to `127.0.0.1:5432`.
- The strategy is `Recreate`: the old pod stops before the new one starts, because only one pod can use the DB volume. `replicaCount` must stay `1`.
- `pvc.yaml` is a PersistentVolumeClaim, so the database survives pod restarts.
- `secret.yaml` holds the DB name, user and password, and is given to both containers.

Check the chart and preview the YAML it produces:

```bash
helm lint helm/webapp
helm template simple-webapp helm/webapp | grep -E "^kind:"
```

You should see a `Secret`, a `PersistentVolumeClaim`, a `Service` and a `Deployment`.

---

## Step 6 – Install with Helm and explore

```bash
helm install simple-webapp helm/webapp --namespace webapp --create-namespace
kubectl -n webapp get pods -w
```

Wait for **`READY 2/2`**, which means both containers are running. Press `Ctrl+C` to stop watching.

### Open the app

OrbStack lets your Mac reach cluster services directly:

- **By name (recommended, stays the same):** <http://simple-webapp.webapp.svc.cluster.local>
- **By Service IP:** run `kubectl -n webapp get svc simple-webapp` and browse to `http://<CLUSTER-IP>`
- **Port-forward (works on any cluster):** `kubectl -n webapp port-forward svc/simple-webapp 8080:80`, then <http://localhost:8080>. Keep that terminal open.

Add some rows.

### Look around

```bash
kubectl -n webapp describe pod -l app.kubernetes.io/name=webapp     # see both containers
kubectl -n webapp logs deploy/simple-webapp -c web                  # app logs
kubectl -n webapp logs deploy/simple-webapp -c db                   # postgres logs
kubectl -n webapp get pvc                                           # the DB volume

# Query the table directly (-c db = run inside the db container)
kubectl -n webapp exec -it deploy/simple-webapp -c db -- psql -U appuser -d appdb -c "SELECT * FROM people;"
```

### Prove the data persists

```bash
kubectl -n webapp delete pod -l app.kubernetes.io/name=webapp
kubectl -n webapp get pods -w        # a new pod appears; wait for 2/2
```

Refresh the page and your rows are still there, because they live on the PVC. Notice that the page was **down** for a few seconds. Part 3 fixes that.

### Try Helm upgrade and rollback

```bash
helm upgrade simple-webapp helm/webapp -n webapp --set appTitle="Hello from Helm upgrade"
helm history simple-webapp -n webapp
helm rollback simple-webapp 1 -n webapp
```

### Hand over to Argo CD

Argo CD will manage the app from Part 2 onwards, so remove the Helm release:

```bash
helm uninstall simple-webapp -n webapp
kubectl -n webapp get pvc      # simple-webapp-db-data is still there
```

The PVC has `helm.sh/resource-policy: keep`, so it survives the uninstall. Argo CD will reuse it, and your rows carry over.

---

# Part 2 – Argo CD and GitOps

## Step 7 – Push the project to GitHub

1. On GitHub, create a new repo named `webapp`. **Public** is simplest; for private, see [Argo CD can't read my repo](#argo-cd-cant-read-my-repo).
2. Edit `argocd/application.yaml` and replace `YOUR_GITHUB_USER` with your GitHub username. Leave every other name lowercase.
3. Push:

   ```bash
   cd webapp
   git init
   git add .
   git commit -m "Web app + helm chart (single pod)"
   git branch -M main
   git remote add origin https://github.com/YOUR_GITHUB_USER/webapp.git
   git push -u origin main
   ```

---

## Step 8 – Install and open Argo CD

### Install

```bash
kubectl create namespace argocd
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

kubectl -n argocd get pods -w      # wait until all are Running, 1/1 (1–3 minutes)
```

### Get the admin password

```bash
argocd admin initial-password -n argocd
```

The username is `admin`.

### Open the UI: choose one option

**Option A – LoadBalancer (recommended on OrbStack; survives restarts, no terminal to keep open)**

```bash
kubectl -n argocd patch svc argocd-server -p '{"spec":{"type":"LoadBalancer"}}'
```

Browse to **<https://argocd-server.argocd.svc.cluster.local>** or **<https://localhost>**.

**Option B – Port-forward**

```bash
kubectl -n argocd port-forward svc/argocd-server 8443:443
```

Leave this terminal **open**, because the address only works while the command runs. Then browse to **<https://localhost:8443>**.

**Either way:**

- Use **https://**, not http://.
- You'll get a certificate warning because Argo CD uses a self-signed certificate. In Chrome, click **Advanced → Proceed** (or type `thisisunsafe` on the warning page). In Safari, click **Show Details → visit this website**.

Can't connect? See [I can't open the Argo CD UI](#i-cant-open-the-argo-cd-ui-localhost8443).

---

## Step 9 – Create the Argo CD Application

```bash
kubectl apply -f argocd/application.yaml
kubectl -n argocd get applications     # wait for: Synced   Healthy
```

In the UI, click **simple-webapp** to see the tree: Deployment → ReplicaSet → Pod, plus the Service, Secret and PVC.

Open <http://simple-webapp.webapp.svc.cluster.local>. Your rows from Step 6 should still be there.

> **If you create the app in the UI instead** (**+ New App**), use exactly these values:
> Application Name `simple-webapp` · Project `default` · Repository URL `https://github.com/YOUR_GITHUB_USER/webapp.git` · Revision `main` · Path `helm/webapp` · Cluster URL `https://kubernetes.default.svc` · Namespace **`webapp`** (required, lowercase) · tick **Auto-Create Namespace**.
>
> Got a sync error about the namespace? See [Troubleshooting](#argo-cd-sync-error-namespace-webapp-is-invalid--must-consist-of-lower-case-alphanumeric-characters).

---

## Step 10 – The GitOps loop

The pattern is always the same: **edit → commit → push → Argo CD deploys.** Argo CD checks Git about every 3 minutes, or you can click **Refresh** in the UI to check immediately.

### A) Change a setting

In `helm/webapp/values.yaml`:

```yaml
appTitle: "Deployed by Argo CD!"
```

```bash
git commit -am "Change title" && git push
```

The pod restarts and the new title appears.

### B) Ship a new app version

1. Change some code, e.g. the `<h2>Add a person</h2>` text in `app/templates/index.html`.
2. Build a **new tag**. Never reuse a tag, or Kubernetes won't notice the change.

   ```bash
   docker build -t webapp:1.0.1 ./app
   ```

3. In `values.yaml` set `web.image.tag: "1.0.1"`, and in `Chart.yaml` set `appVersion: "1.0.1"`.
4. Commit and push.

### C) Watch self-heal

```bash
kubectl -n webapp scale deploy/simple-webapp --replicas=0
kubectl -n webapp get pods -w
```

Within seconds Argo CD restores the replica count, because Git is the source of truth (`selfHeal: true`).

> **Committing straight to `main`** is fine while you're learning the loop. In Part 3 you'll switch to the team approach: make changes on a **branch**, open a **Pull Request**, and merge to deploy.

---

# Part 3 – Move the database to its own pod + add an image

## Step 11 – Why separate pods

| DB in the same pod (Parts 1–2) | DB in its own pod (Part 3) |
|---|---|
| Web and DB always restart together | Each restarts independently |
| Only **1** web pod possible (the volume can only attach once) | Scale web pods freely |
| `Recreate` deploys = a few seconds of downtime | `RollingUpdate` = zero-downtime deploys |
| App connects to `127.0.0.1` | App connects to a **Service name** (`simple-webapp-db`) |

New concepts in this part:

- **StatefulSet**: like a Deployment, but each pod gets a stable name (`simple-webapp-db-0`) and its own volume that stays with it.
- **Headless Service** (`clusterIP: None`): gives the DB a DNS name the web pods can use.
- **Init container**: runs before the main container. Here, `wait-for-db` blocks until Postgres answers.
- **Feature branch + Pull Request**: you make the change on a branch, review it, then merge it into `main` to deploy. This is how teams use GitOps.

---

## Step 12 – What changes

Everything you need is in `part3/helm-webapp/`. If your repo came from an older zip without that folder, copy `part3/` in from the latest zip first.

| File | Change |
|---|---|
| `templates/deployment.yaml` | Only the `web` container now. Adds the `wait-for-db` init container, switches to `RollingUpdate`, sets `DB_HOST` to `simple-webapp-db`. |
| `templates/db-statefulset.yaml` | **New.** Postgres in a StatefulSet with its own volume (`volumeClaimTemplates`). |
| `templates/db-service.yaml` | **New.** Headless Service so the web pods can find the DB by name. |
| `templates/pvc.yaml` | **Deleted.** The StatefulSet creates its own PVC (`data-simple-webapp-db-0`). |
| `templates/_helpers.tpl` | New `dbFullname` and `dbSelectorLabels` helpers. The web `selectorLabels` are **unchanged**, because a Deployment's selector can't be changed. |
| `values.yaml` | `replicaCount` moves under `web:` (now `2`), `persistence` moves under `db:`, `bannerImage: "team.svg"`, tag `1.1.0`. |
| `Chart.yaml` | Chart `0.2.0`, app `1.1.0`. |

The **image under the table** is turned on by `bannerImage: "team.svg"`. The app shows `app/static/team.svg` whenever that value is set.

### How the workflow fits together

```
main ──●────────────────────────────────●──▶   Argo CD deploys whatever is on main
       │ tag: part2-single-pod          ▲
       │                                │ merge Pull Request (Step 19) → rollout
       └──● part3-separate-db ──────────┘
          Steps 13–18: change, build, check, push branch, open PR
          (nothing deploys yet)
```

Argo CD watches **only `main`** (`targetRevision: main`). Work on the branch is safe: nothing reaches the cluster until you merge.

---

## Step 13 – Bookmark Part 2 and create a branch

First make sure `main` is clean and up to date:

```bash
git checkout main
git pull
git status            # should say "nothing to commit, working tree clean"
```

**Tag the working Part 2 version**, so you can always find it again:

```bash
git tag part2-single-pod
git push origin part2-single-pod
```

**Create a feature branch** for the Part 3 work:

```bash
git checkout -b part3-separate-db
git branch --show-current       # part3-separate-db
```

All the file changes in Steps 15–18 happen on this branch.

---

## Step 14 – Back up your table data

When the change is merged, Argo CD will delete the old volume (`simple-webapp-db-data`), and the StatefulSet starts with a new, empty volume. Save your rows now, while the old pod is still running:

```bash
kubectl -n webapp exec deploy/simple-webapp -c db -- \
  pg_dump -U appuser -d appdb --data-only -t people -t people_id_seq > people-backup.sql

cat people-backup.sql      # check your rows are in there
```

`people-backup.sql` is in `.gitignore`, so it won't be committed.

> **Timing:** the old database keeps running until you merge in Step 19. If you add rows in the app after this backup, run the backup again just before merging.

---

## Step 15 – Swap in the Part 3 chart

On the `part3-separate-db` branch, from the root of your repo:

```bash
git branch --show-current            # double-check: part3-separate-db
cp -R part3/helm-webapp/. helm/webapp/
git rm helm/webapp/templates/pvc.yaml
git status        # review: deployment, values, Chart, _helpers, NOTES changed; 2 new db-* files; pvc deleted
```

If you'd customised `values.yaml` in Part 2 (e.g. `appTitle`), put your values back into the new file. Keep **your** `argocd/application.yaml`, which doesn't change.

---

## Step 16 – Build the new image version

```bash
docker build -t webapp:1.1.0 ./app
docker images | grep webapp      # 1.0.0 and 1.1.0
```

Always use a new tag when you rebuild, so Kubernetes picks up your latest code. Your existing `1.0.0` might have been built from older code that can't show the image.

Building the image doesn't change anything that's running. The cluster keeps using `1.0.0` until `values.yaml` on `main` says `1.1.0`.

---

## Step 17 – Check the chart

```bash
helm lint helm/webapp
helm template simple-webapp helm/webapp | grep -E "^kind:"
```

You should now see a `Secret`, two `Service`s, a `Deployment` and a `StatefulSet`, and **no** standalone `PersistentVolumeClaim`.

Compare the branch with `main` to see every change in one place:

```bash
git diff main --stat
git diff main -- helm/webapp/values.yaml
```

---

## Step 18 – Commit, push the branch and open a Pull Request

```bash
git add .
git commit -m "Part 3: move DB to its own StatefulSet pod, add banner image"
git push -u origin part3-separate-db
```

**Nothing deploys yet.** In Argo CD the app still shows `Synced` against the old commit on `main`, and `kubectl -n webapp get pods` still shows the `2/2` pod.

Open a Pull Request on GitHub:

1. Go to your repo. GitHub shows a banner, **"part3-separate-db had recent pushes"**. Click **Compare & pull request**.
   (Or: **Pull requests → New pull request**, base `main` ← compare `part3-separate-db`.)
2. Give it a title, e.g. *Part 3: DB in its own pod*.
3. Open the **Files changed** tab and review the diff. This is exactly what Argo CD will apply.
4. Click **Create pull request**. Don't merge yet.

---

## Step 19 – Merge and watch Argo CD roll it out

Before merging, check:

- [ ] Backup taken (Step 14) and still current
- [ ] `webapp:1.1.0` built (Step 16)
- [ ] `helm lint` passed (Step 17)

On the Pull Request page, click **Merge pull request → Confirm merge**. GitHub then offers **Delete branch**, which is safe to click.

Prefer the command line? This does the same:

```bash
git checkout main
git merge part3-separate-db
git push
```

Click **Refresh** in Argo CD (or wait about 3 minutes). Argo CD sees the new commit on `main` and syncs. Watch:

```bash
kubectl -n webapp get pods -L app.kubernetes.io/component -w
```

What you'll see:

1. `simple-webapp-db-0` starts (component `database`) and reaches `1/1`.
2. Two new web pods show `Init:0/1` (waiting for the DB), then `1/1` (component `web`).
3. The old `2/2` pod is removed, and the old PVC is deleted with it.

In the Argo CD tree, the Deployment and StatefulSet are now separate branches. The app's **Last Sync** shows the merge commit.

```bash
kubectl -n webapp get deploy,statefulset,svc,pvc
```

**Update your local copy**, so `main` on your Mac matches GitHub:

```bash
git checkout main
git pull
git branch -d part3-separate-db              # tidy up the local branch
```

> **If something goes wrong:** open the merged Pull Request on GitHub and click **Revert**. That creates a new Pull Request that undoes the change. Merge it, and Argo CD puts the single-pod version back. See [Rolling back Part 3](#rolling-back-part-3) for what happens to your data.

---

## Step 20 – Restore your data

Do this **before** adding new rows in the app, to avoid duplicate IDs:

```bash
kubectl -n webapp exec -i simple-webapp-db-0 -- \
  psql -U appuser -d appdb < people-backup.sql
```

Refresh the page. Your rows are back, and the image now appears under the table.

---

## Step 21 – Explore the new layout

**See load balancing.** The footer says "Served by pod …". Browsers reuse connections, so use curl to see both pods answer:

```bash
for i in $(seq 1 8); do
  curl -s http://simple-webapp.webapp.svc.cluster.local | grep -o 'Served by pod <code>[^<]*' | sed 's/.*<code>//'
done
```

**Kill the DB pod.** It comes back with the **same name** and **same volume**, so the data survives:

```bash
kubectl -n webapp delete pod simple-webapp-db-0
kubectl -n webapp get pods -w
```

**Kill a web pod.** The other one keeps serving, so there's no downtime (compare with Step 6):

```bash
kubectl -n webapp delete pod -l app.kubernetes.io/component=web --wait=false
```

**Connect to the DB.** It's its own pod now, so there's no `-c db`:

```bash
kubectl -n webapp exec -it simple-webapp-db-0 -- psql -U appuser -d appdb -c "SELECT * FROM people;"
kubectl -n webapp logs simple-webapp-db-0
kubectl -n webapp logs deploy/simple-webapp -c wait-for-db     # init container output
```

---

## Step 22 – More GitOps practice (with branches)

From now on, use the same branch → Pull Request → merge flow for every change:

```bash
git checkout main && git pull
git checkout -b scale-web-to-3
# edit helm/webapp/values.yaml: web.replicaCount: 3
git commit -am "Scale web tier to 3" && git push -u origin scale-web-to-3
# open a PR on GitHub → review → merge → Argo CD deploys
git checkout main && git pull
```

Ideas to practise with:

**Scale the web tier.** Set `web.replicaCount: 3`. After the merge, a third web pod appears in the curl loop.

**Change the image under the table.** There are two ways:

- **Use a URL (no rebuild):** set `bannerImage: "https://…/picture.jpg"`. The image must be publicly reachable, because your browser loads it.
- **Use your own file:** put e.g. `office.png` in `app/static/`, set `bannerImage: "office.png"`, and bump `web.image.tag` to `"1.1.1"`. Run `docker build -t webapp:1.1.1 ./app` before you merge.
- To remove the image, set `bannerImage: ""`.

**Zero-downtime deploys.** Ship a new version, as in Step 10B but on a branch, and run the curl loop while the merge rolls out. Responses keep coming throughout.

**Practise a rollback.** Merge a harmless change (e.g. a new `appTitle`), then click **Revert** on its Pull Request and merge the revert. Watch Argo CD roll it back.

---

# Troubleshooting

> Commands differ slightly between layouts:
> **Part 1–2** (one pod): DB commands use `deploy/simple-webapp -c db`.
> **Part 3** (separate pods): DB commands use `simple-webapp-db-0`.

### General approach

When something's wrong, run these in order:

```bash
kubectl -n argocd get applications                          # Sync / Health status
kubectl -n webapp get pods -L app.kubernetes.io/component   # what's running
kubectl -n webapp describe pod <pod-name>                   # the "Events" section at the bottom explains most problems
kubectl -n webapp logs <pod-name> [-c <container>]          # app output
kubectl -n webapp get events --sort-by=.lastTimestamp       # recent cluster events
```

In the Argo CD UI, click the app to see sync status and events. Clicking any resource in the tree shows its live YAML, events and logs.

### Argo CD sync error: `Namespace "WebApp" is invalid … must consist of lower case alphanumeric characters`

**Cause:** the Application's destination namespace has capital letters. Kubernetes names must be lowercase letters, numbers and `-`.

**Fix:** set it to `webapp`.

- **File:** in `argocd/application.yaml`, set `spec.destination.namespace: webapp`, then run `kubectl apply -f argocd/application.yaml`.
- **UI:** click the app → **Details → Edit** → Destination Namespace `webapp` → **Save**.

The same rule applies to `metadata.name` and `releaseName`. The GitHub `repoURL` is the exception: it isn't case-sensitive, so `…/WebApp.git` is fine. The failed sync created nothing, so there's nothing to clean up.

### Argo CD sync error: `InvalidSpecError: Namespace for simple-webapp … is missing`

**Cause:** the Application has **no** destination namespace. The chart's templates don't set one, so Argo CD doesn't know where to put them. This often happens after deleting the bad value from the previous error.

**Fix:** add it back:

```yaml
spec:
  destination:
    server: https://kubernetes.default.svc
    namespace: webapp
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
```

```bash
kubectl apply -f argocd/application.yaml
argocd app sync simple-webapp       # or Refresh → Sync in the UI

# Confirm (should print: webapp)
kubectl -n argocd get application simple-webapp -o jsonpath='{.spec.destination.namespace}{"\n"}'
```

### I can't open the Argo CD UI (localhost:8443)

Work through these in order:

1. **Is the port-forward running?** `localhost:8443` only works while `kubectl -n argocd port-forward svc/argocd-server 8443:443` is running in an open terminal. It should print `Forwarding from 127.0.0.1:8443 -> 8080` and keep running. Run other commands in a **new** tab.
2. **Did the port-forward exit with an error?**
   - `address already in use`: pick another local port, e.g. `9443:443`, then browse to `https://localhost:9443`.
   - `pod is not running` / `no endpoints`: Argo CD isn't ready. Go to the next check.
   - It **stops by itself later**: port-forwards end when the pod restarts. Run it again.
3. **Is Argo CD running?** `kubectl -n argocd get pods` should show every pod `Running`. If `argocd-server` isn't:

   ```bash
   kubectl -n argocd describe pod -l app.kubernetes.io/name=argocd-server
   kubectl -n argocd logs deploy/argocd-server
   ```

4. **Are you using https?** The address must be `https://localhost:8443`, not `http://`.
5. **Certificate warning?** That's expected. Click through it (see Step 8).
6. **Skip port-forward entirely:** use Option A in Step 8 (LoadBalancer), then <https://argocd-server.argocd.svc.cluster.local>.

### How do I see what IP and port a pod/container is using?

The **IP belongs to the pod**. Every container in a pod shares that IP (in Part 1, web and db share one IP), and each listens on its own port.

```bash
# Pod IPs
kubectl -n webapp get pods -o wide

# Ports each container exposes
kubectl -n webapp get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .spec.containers[*]}{.name}:{.ports[*].containerPort} {end}{"\n"}{end}'

# Services: stable IP + port
kubectl -n webapp get svc

# Which pod IP:port each Service actually forwards to
kubectl -n webapp get endpoints

# Everything in one readable view (look for IP:, Port:)
kubectl -n webapp describe pod <pod-name>
```

Expected values: the web container on **8000**, Postgres on **5432**, and the `simple-webapp` Service on **80** (it forwards to 8000).

Browsing from your Mac with OrbStack:

| Address | Example | Stable? |
|---|---|---|
| Pod IP | `http://<pod-IP>:8000` | ❌ changes every restart or sync |
| Service IP | `http://<CLUSTER-IP>` | ✅ until the Service is deleted |
| Service name | `http://simple-webapp.webapp.svc.cluster.local` | ✅ best to bookmark |

Check what's listening inside a container:

```bash
# Postgres image includes netstat
kubectl -n webapp exec deploy/simple-webapp -c db -- netstat -tln     # Part 1–2
kubectl -n webapp exec simple-webapp-db-0 -- netstat -tln             # Part 3

# The slim Python image has no netstat; gunicorn logs "Listening at: http://0.0.0.0:8000"
kubectl -n webapp logs deploy/simple-webapp -c web | head
```

### The app address stopped working after a sync or restart

You were probably using a **pod IP**, which changes whenever a pod is replaced. Use the Service name instead: <http://simple-webapp.webapp.svc.cluster.local>.

### Pod status problems

| Status | Meaning and fix |
|---|---|
| `ErrImagePull` / `ImagePullBackOff` | The image tag in `values.yaml` doesn't exist locally. Run `docker images \| grep webapp` and build that exact tag. Never use `latest`. |
| `1/2` READY (Part 1) | One container is unhealthy. Run `describe pod`, then `logs … -c web` or `-c db`. |
| `Init:0/1` for a long time (Part 3) | The web pod is waiting for the DB. Check `kubectl -n webapp logs <web-pod> -c wait-for-db` and `kubectl -n webapp logs simple-webapp-db-0`. |
| `CrashLoopBackOff` | The container starts then dies. Run `kubectl -n webapp logs <pod> [-c <container>] --previous` to see why. |
| `Pending` | Usually the volume. Check `kubectl -n webapp get pvc` and `kubectl -n webapp describe pvc <name>`. |
| `Running` but not ready | The readiness probe is failing. For web pods, `/ready` fails when the DB is unreachable. |

### No image under the table

- **Part 1–2:** that's expected, because `bannerImage` is `""`.
- **Part 3:** check `bannerImage: "team.svg"` in `values.yaml`, and that `web.image.tag` is `1.1.0` and you built it (Step 16). Check the change is merged into `main`, not just on your branch. Pods still running an old image won't have the feature.

### Argo CD shows `OutOfSync` or doesn't pick up my change

- Did you **push**? Run `git log origin/main -1` to check.
- Click **Refresh** in the UI, or wait about 3 minutes.
- Is `targetRevision` (`main`) the branch you pushed to?
- Is `path` (`helm/webapp`) the folder that contains `Chart.yaml`?
- To see what differs, click the app → **App Diff**.

### Argo CD sync error: `field is immutable`

You changed a Deployment's or StatefulSet's `selector` labels, which Kubernetes doesn't allow. Revert `selectorLabels` / `dbSelectorLabels` in `_helpers.tpl` to the originals. If you must change them, delete that Deployment or StatefulSet in the Argo CD UI and let it re-create it.

### Argo CD can't read my repo

The app shows `Unknown`, or a `repository not found` / `authentication required` error.

- Check `repoURL` is correct and ends in `.git`.
- **Private repo:** add credentials using a GitHub personal access token:

  ```bash
  argocd login argocd-server.argocd.svc.cluster.local --insecure --username admin   # or localhost:8443
  argocd repo add https://github.com/YOUR_GITHUB_USER/webapp.git \
    --username YOUR_GITHUB_USER --password <personal-access-token>
  ```

### Database login fails after I changed the password

Postgres only sets the password when its volume is **first created**. You can do either of these:

- Put the old password back in `values.yaml`.
- Reset it inside the DB: `psql … -c "ALTER USER appuser PASSWORD 'newpass';"`, using the DB command for your layout.
- Start fresh (**this deletes the data**): delete the DB PVC, then the pod.

### I pushed my branch but nothing deployed

That's expected. Argo CD only deploys `main` (`targetRevision: main`). Open a Pull Request and merge it (Steps 18–19). To check what Argo CD is tracking:

```bash
kubectl -n argocd get application simple-webapp -o jsonpath='{.spec.source.targetRevision}{"\n"}'   # main
git log origin/main -1 --oneline        # the commit Argo CD should be on
```

Compare that commit with **Last Sync** in the Argo CD UI.

### I made changes on the wrong branch

Run `git branch --show-current` to see where you are.

- **Not committed yet:** `git stash`, `git checkout <right-branch>`, then `git stash pop`.
- **Already committed to `main` but not pushed:** `git branch part3-separate-db` (saves the work to the branch), then `git reset --hard origin/main` (resets `main`), then `git checkout part3-separate-db`.
- **Already pushed to `main`:** Argo CD has deployed it. Either carry on, or use `git revert <commit>` and push to undo it.

### Pull Request shows a merge conflict

`main` changed after you created the branch. Update the branch:

```bash
git checkout part3-separate-db
git pull origin main          # merge the latest main into your branch
# fix the files git lists as conflicted, then:
git add . && git commit && git push
```

### Rolling back Part 3

On GitHub, open the merged Part 3 Pull Request and click **Revert**, then merge the new Pull Request. Argo CD redeploys the single-pod version.

**Your data:** the single-pod version creates a **new, empty** `simple-webapp-db-data` volume, because the old one was deleted in Step 19. Back up first, then restore after the rollback:

```bash
# before reverting (Part 3 layout)
kubectl -n webapp exec simple-webapp-db-0 -- \
  pg_dump -U appuser -d appdb --data-only -t people -t people_id_seq > people-backup.sql

# after the rollback is running (single-pod layout)
kubectl -n webapp exec -i deploy/simple-webapp -c db -- psql -U appuser -d appdb < people-backup.sql
```

To look at the Part 2 code at any time without changing anything: `git checkout part2-single-pod`. Run `git checkout main` to return.

### Part 3 restore error: `duplicate key value violates unique constraint`

You added rows before restoring. Clear the table (`DELETE FROM people;`), then restore again.

### Part 3: old PVC `simple-webapp-db-data` still listed

Harmless. Once you've restored, delete it: `kubectl -n webapp delete pvc simple-webapp-db-data`.

---

# Command cheat sheet

```bash
# What's running
kubectl -n webapp get pods -o wide -L app.kubernetes.io/component
kubectl -n webapp get deploy,statefulset,svc,endpoints,pvc

# Logs
kubectl -n webapp logs deploy/simple-webapp -c web -f
kubectl -n webapp logs deploy/simple-webapp -c db -f     # Part 1–2
kubectl -n webapp logs simple-webapp-db-0 -f             # Part 3

# DB access
kubectl -n webapp exec -it deploy/simple-webapp -c db -- psql -U appuser -d appdb   # Part 1–2
kubectl -n webapp exec -it simple-webapp-db-0 -- psql -U appuser -d appdb           # Part 3

# Shell in the web container
kubectl -n webapp exec -it deploy/simple-webapp -c web -- sh

# Argo CD
kubectl -n argocd get applications
argocd app get simple-webapp
argocd app sync simple-webapp
argocd app diff simple-webapp

# Git: branch → PR → merge workflow
git checkout main && git pull                 # start from the latest main
git checkout -b my-change                     # new branch
git branch --show-current                     # where am I?
git diff main --stat                          # what's different from main
git push -u origin my-change                  # push branch, then open a PR on GitHub
git checkout main && git pull                 # after merging on GitHub
git branch -d my-change                       # delete the local branch
git tag                                       # list bookmarks (e.g. part2-single-pod)

# Helm (render without installing)
helm lint helm/webapp
helm template simple-webapp helm/webapp
```

---

# Clean up

```bash
kubectl delete -f argocd/application.yaml      # Argo CD removes the app
kubectl delete namespace webapp                # removes the remaining PVCs too
kubectl delete namespace argocd                # removes Argo CD
```

---

# Learning notes

After Part 3, the project follows several good practices: a stateless web tier, the DB in a StatefulSet, probes, an init container, and GitOps. Real production setups usually go further:

- Use a managed database, or a Postgres **operator** (e.g. CloudNativePG) for backups, replicas and failover.
- Push images to a **registry** (GitHub Container Registry, Docker Hub). Build them in CI (e.g. GitHub Actions), and have CI bump the image tag in Git.
- Keep secrets out of Git with Sealed Secrets, External Secrets Operator or Vault.
- Add an **Ingress** for a real URL.
- Use separate values files per environment (`values-dev.yaml`, `values-prod.yaml`).

Good next exercises: add an Ingress template, add a `values-dev.yaml`, or add a nightly `pg_dump` CronJob to back up the database.
