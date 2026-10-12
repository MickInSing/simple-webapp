# Web App → Docker → Helm → Kubernetes → Argo CD (on OrbStack)

A step-by-step learning project. By the end you will have:

- A **Flask web app** that shows an image and a table you can add/edit/delete (6 fields: name, email, role, department, location, start date)
- A **PostgreSQL database** running as a **second container in the same pod** as the app
- A **Helm chart** that deploys it all
- **Argo CD** watching your Git repo and deploying changes automatically (GitOps)

```
┌──────────────────────── Pod: webapp ────────────────────────┐
│  ┌──────────────┐   127.0.0.1:5432   ┌───────────────────┐  │
│  │ web (Flask)  │ ─────────────────▶ │ db (Postgres 16)  │  │
│  │ port 8000    │                    │ data on a PVC     │  │
│  └──────────────┘                    └───────────────────┘  │
└──────────────────────────────▲──────────────────────────────┘
                               │ Service (port 80)
                        kubectl port-forward → http://localhost:8080
```

## Project layout

```
webapp/
├── app/                      # the web application
│   ├── app.py                # Flask routes + database code
│   ├── templates/            # HTML pages (index.html, edit.html)
│   ├── static/               # logo.svg (the image) + style.css
│   ├── requirements.txt
│   └── Dockerfile
├── compose.yaml              # run locally with Docker before Kubernetes
├── helm/webapp/              # the Helm chart
│   ├── Chart.yaml
│   ├── values.yaml           # all the settings you'll tweak
│   └── templates/            # deployment, service, pvc, secret
└── argocd/application.yaml   # tells Argo CD where your chart lives
```

---

## Step 0 – Prerequisites

1. **Enable Kubernetes in OrbStack**: OrbStack → Settings → Kubernetes → *Enable Kubernetes*. Wait until it says running.
2. Install the tools (with Homebrew):

   ```bash
   brew install kubectl helm git argocd
   ```

3. Check everything works:

   ```bash
   docker version
   kubectl config use-context orbstack
   kubectl get nodes          # should show 1 node, STATUS Ready
   helm version
   ```

4. A **GitHub account** (Argo CD pulls your chart from Git).

---

## Step 1 – Understand the app (read, don't skip)

Open `app/app.py`. Key ideas:

- Config comes from **environment variables** (`DB_HOST`, `DB_PASSWORD`, `APP_TITLE`…). Kubernetes/Helm will set these.
- `init_db()` waits for Postgres to be ready, then creates the `people` table if it doesn't exist.
- Routes: `/` (list + add form), `/add`, `/edit/<id>`, `/delete/<id>`.
- `/healthz` and `/ready` are for Kubernetes **liveness** and **readiness** probes.

---

## Step 2 – Run it locally with Docker Compose

This proves the app works before Kubernetes gets involved.

```bash
cd webapp
docker compose up --build
```

Open <http://localhost:8000>. Add a few rows, edit one, delete one.

Stop it with `Ctrl+C`, then clean up:

```bash
docker compose down -v      # -v also deletes the local test database
```

> Compose also built the image `webapp:1.0.0`. Because OrbStack's Kubernetes shares the same Docker engine, **the cluster can use this image directly — no registry needed.**

---

## Step 3 – Build the image for Kubernetes

(Already done by Compose, but here's the explicit command you'll use from now on.)

```bash
docker build -t webapp:1.0.0 ./app
docker images | grep webapp
```

> Why not `:latest`? Kubernetes treats `latest` as "always pull from a registry", which would fail since the image only exists locally. A real version tag + `imagePullPolicy: IfNotPresent` uses the local image.

---

## Step 4 – Explore the Helm chart

- `values.yaml` – the settings. Templates read them as `{{ .Values.something }}`.
- `templates/deployment.yaml` – **one pod with two containers**: `web` and `db`. They share a network, so the app connects to `127.0.0.1:5432`.
- `templates/pvc.yaml` – a PersistentVolumeClaim so the database survives pod restarts.
- `templates/secret.yaml` – DB name/user/password, injected into both containers.
- `templates/service.yaml` – a stable address for the pod.

Check the chart and see the YAML it generates:

```bash
helm lint helm/webapp
helm template webapp helm/webapp | less
```

---

## Step 5 – Install with Helm

```bash
helm install webapp helm/webapp --namespace webapp --create-namespace
```

Watch it start:

```bash
kubectl -n webapp get pods -w
```

Wait for **`READY 2/2`** — that's your two containers. `Ctrl+C` to stop watching.

Open the app:

```bash
kubectl -n webapp port-forward svc/webapp 8080:80
```

Browse to <http://localhost:8080>. Add some rows.

### Explore what's running

```bash
kubectl -n webapp describe pod -l app.kubernetes.io/name=webapp   # see both containers
kubectl -n webapp logs deploy/webapp -c web                        # app logs
kubectl -n webapp logs deploy/webapp -c db                         # postgres logs
kubectl -n webapp get pvc                                          # the DB volume

# Look inside the database directly
kubectl -n webapp exec -it deploy/webapp -c db -- psql -U appuser -d appdb -c "SELECT * FROM people;"
```

### Prove the data persists

```bash
kubectl -n webapp delete pod -l app.kubernetes.io/name=webapp
kubectl -n webapp get pods -w        # a new pod appears, wait for 2/2
```

Re-run the port-forward and refresh — your rows are still there (they live on the PVC).

### Try a Helm upgrade

```bash
helm upgrade webapp helm/webapp -n webapp --set appTitle="Hello from Helm upgrade"
helm history webapp -n webapp
helm rollback webapp 1 -n webapp     # go back to revision 1
```

### Hand over to Argo CD

Argo CD will manage the app from now on, so remove the Helm release:

```bash
helm uninstall webapp -n webapp
```

(The PVC has `helm.sh/resource-policy: keep`, so your data stays and Argo CD will reuse it.)

---

## Step 6 – Push the project to GitHub

1. On GitHub, create a new **public** repo named `webapp` (public = no credentials needed in Argo CD; private works too, see Troubleshooting).
2. Edit `argocd/application.yaml` and replace `YOUR_GITHUB_USER` with your username.
3. Push:

   ```bash
   cd webapp
   git init
   git add .
   git commit -m "Initial web app + helm chart"
   git branch -M main
   git remote add origin https://github.com/YOUR_GITHUB_USER/webapp.git
   git push -u origin main
   ```

---

## Step 7 – Install Argo CD

```bash
kubectl create namespace argocd
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```

Wait for everything to be running (1–3 minutes):

```bash
kubectl -n argocd get pods -w
```

Get the admin password:

```bash
argocd admin initial-password -n argocd
```

Open the UI (leave this running in its own terminal tab):

```bash
kubectl -n argocd port-forward svc/argocd-server 8443:443
```

Browse to <https://localhost:8443>, accept the self-signed certificate warning, log in as **admin** with that password.

---

## Step 8 – Create the Argo CD Application

```bash
kubectl apply -f argocd/application.yaml
```

In the Argo CD UI you'll see the **webapp** app appear and sync automatically. Click it to see the tree: Deployment → ReplicaSet → Pod, plus Service, Secret, PVC.

Or from the CLI:

```bash
kubectl -n argocd get applications
```

Open the app again (port 8080 is free since Step 5's forward was stopped):

```bash
kubectl -n webapp port-forward svc/webapp 8080:80
```

Your old rows should still be there.

---

## Step 9 – The GitOps loop (the fun part)

### A) Change config through Git

Edit `helm/webapp/values.yaml`:

```yaml
appTitle: "Deployed by Argo CD!"
```

```bash
git commit -am "Change title"
git push
```

Argo CD polls Git about every 3 minutes (or click **Refresh** → **Sync** in the UI). The pod restarts with the new title.

### B) Ship a new app version

1. Make a code change, e.g. in `app/templates/index.html` change the `<h2>Add a person</h2>` text.
2. Build a new image tag:

   ```bash
   docker build -t webapp:1.0.1 ./app
   ```

3. Update `helm/webapp/values.yaml` → `web.image.tag: "1.0.1"` (and `appVersion` in `Chart.yaml`).
4. Commit and push. Argo CD rolls out the new version.

### C) Watch self-heal

Try changing something by hand:

```bash
kubectl -n webapp scale deploy/webapp --replicas=0
```

Within seconds Argo CD sets it back to 1, because Git is the source of truth (`selfHeal: true`).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ErrImagePull` / `ImagePullBackOff` | Image tag in `values.yaml` doesn't exist locally. Run `docker images \| grep webapp` and build the right tag. Make sure the tag isn't `latest`. |
| Pod shows `1/2` READY | Check which container: `kubectl -n webapp describe pod ...`, then `kubectl logs ... -c web` or `-c db`. |
| Pod `Pending` | PVC not bound: `kubectl -n webapp get pvc` and `kubectl describe pvc`. |
| Argo CD app "Unknown" / repo error | Check `repoURL` in `argocd/application.yaml`. For a **private repo**: `argocd login localhost:8443 --insecure`, then `argocd repo add https://github.com/USER/webapp.git --username USER --password <GitHub personal access token>`. |
| Changed the DB password but login fails | Postgres only reads the password on first start of an empty volume. Delete the PVC to start fresh (data is lost). |
| Port-forward stops | It ends when the pod restarts. Just run it again. |

Tip: OrbStack also lets your Mac reach cluster services directly, e.g. <http://webapp.webapp.svc.cluster.local>, so port-forward is optional there.

---

## Clean up

```bash
kubectl delete -f argocd/application.yaml      # Argo CD removes the app
kubectl delete namespace webapp                # removes the kept PVC too
kubectl delete namespace argocd                # removes Argo CD
```

---

## Learning notes: what a production setup would do differently

This project puts the database in the same pod on purpose so you can learn multi-container pods. In real systems you'd usually:

- Run the database separately (its own **StatefulSet**, or a managed database) so the app can scale to many replicas independently.
- Store images in a **registry** (GitHub Container Registry, Docker Hub) and build them in CI (e.g. GitHub Actions) that also bumps the image tag in Git.
- Keep secrets out of Git (Sealed Secrets, External Secrets Operator, Vault).
- Add an **Ingress** for a real URL instead of port-forward.

Good next exercises: add an Ingress template to the chart, add a `values-dev.yaml` / `values-prod.yaml`, or move Postgres into its own StatefulSet.
