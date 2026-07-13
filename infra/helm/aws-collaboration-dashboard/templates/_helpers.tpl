{{/* Chart naming and shared labels. */}}
{{- define "aws-collaboration-dashboard.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "aws-collaboration-dashboard.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := include "aws-collaboration-dashboard.name" . }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "aws-collaboration-dashboard.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "aws-collaboration-dashboard.labels" -}}
helm.sh/chart: {{ include "aws-collaboration-dashboard.chart" . }}
{{ include "aws-collaboration-dashboard.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "aws-collaboration-dashboard.selectorLabels" -}}
app.kubernetes.io/name: {{ include "aws-collaboration-dashboard.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "aws-collaboration-dashboard.configMapName" -}}
{{- printf "%s-config" (include "aws-collaboration-dashboard.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "aws-collaboration-dashboard.databaseSecretName" -}}
{{- printf "%s-database" (include "aws-collaboration-dashboard.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "aws-collaboration-dashboard.postgresServiceName" -}}
{{- printf "%s-postgres" (include "aws-collaboration-dashboard.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "aws-collaboration-dashboard.postgresHeadlessServiceName" -}}
{{- printf "%s-postgres-headless" (include "aws-collaboration-dashboard.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "aws-collaboration-dashboard.apiServiceName" -}}
{{- printf "%s-api" (include "aws-collaboration-dashboard.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "aws-collaboration-dashboard.webServiceName" -}}
{{- printf "%s-web" (include "aws-collaboration-dashboard.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "aws-collaboration-dashboard.bootstrapJobName" -}}
{{- printf "%s-bootstrap-r%d" (include "aws-collaboration-dashboard.fullname" .) .Release.Revision | trunc 63 | trimSuffix "-" }}
{{- end }}
