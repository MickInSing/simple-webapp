{{/* Common name used for the web resources */}}
{{- define "webapp.fullname" -}}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Name used for the database resources (StatefulSet, Service) */}}
{{- define "webapp.dbFullname" -}}
{{- printf "%s-db" (include "webapp.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Labels put on every resource */}}
{{- define "webapp.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/*
Labels used to match the WEB pods.
Unchanged from Part 1 on purpose: a Deployment's selector can't be changed after creation.
*/}}
{{- define "webapp.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* Labels used to match the DATABASE pod (different name, so it never matches the web selector) */}}
{{- define "webapp.dbSelectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}-db
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
