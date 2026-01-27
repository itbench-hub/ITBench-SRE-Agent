# Kubernetes Data Source Reference

## Kubernetes Resources (via Kubernetes MCP)

The Kubernetes MCP server provides direct access to live cluster state via kubectl-like operations. Use it to query resources, fetch logs, and inspect cluster configuration.

### Available Operations

**Resource Queries:**
- Get resource status (pods, deployments, services, nodes, etc.)
- List resources by namespace or cluster-wide
- Describe resources for detailed information
- Get resource specifications and manifests

**Live Diagnostics:**
- Fetch pod logs (current and previous containers)
- Stream real-time logs
- Get pod events
- Check resource health and readiness

**Cluster State:**
- Query cluster-wide events
- Inspect node status and capacity
- Check resource quotas and limits
- View service endpoints and networking

### Common Query Patterns

**Pod Status and Events:**
```
Get all pods in namespace otel-demo
Describe pod <pod-name> in namespace otel-demo
Get events for pod <pod-name> in namespace otel-demo
```

**Logs:**
```
Get logs for pod <pod-name> in namespace otel-demo
Get logs for pod <pod-name> container <container-name>
Get previous logs for pod <pod-name> (from crashed container)
Get last 100 lines of logs for pod <pod-name>
```

**Deployments and ReplicaSets:**
```
Get all deployments in namespace otel-demo
Describe deployment <deployment-name>
Get replica sets for deployment <deployment-name>
```

**Services and Networking:**
```
Get all services in namespace otel-demo
Describe service <service-name>
Get endpoints for service <service-name>
```

**Node and Cluster Status:**
```
Get all nodes
Describe node <node-name>
Get cluster events in the last hour
```

### Investigation Patterns

**1. Identify Failing Pods:**
- Query all pods in the target namespace
- Filter for pods with non-Running status (Pending, CrashLoopBackOff, Error)
- Check pod conditions (Ready, ContainersReady, PodScheduled)

**2. Analyze Pod Failures:**
- Describe the failing pod for detailed status
- Get pod events to see recent lifecycle events
- Fetch logs from failed containers
- Get previous logs if container restarted

**3. Check Resource Constraints:**
- Describe nodes to check capacity and allocatable resources
- Check pod resource requests vs node capacity
- Look for eviction events or OOM kills

**4. Investigate Networking Issues:**
- Describe services to verify selectors and endpoints
- Check service endpoints to see if pods are registered
- Review network policies if applicable

**5. Configuration Analysis:**
- Get deployment/statefulset specs
- Check ConfigMap and Secret references
- Verify environment variables and volume mounts

### Data Collection Tasks

**Query Kubernetes** for:
- Pod status and events → Write to `$WORKSPACE_DIR/k8s_events.json`
- Deployment/StatefulSet specs → Write to `$WORKSPACE_DIR/k8s_specs.json`
- Service topology and endpoints → Write to `$WORKSPACE_DIR/app.json`
- Pod logs (errors) → Write to `$WORKSPACE_DIR/k8s_logs.json`
- Node status → Write to `$WORKSPACE_DIR/k8s_nodes.json`

### Key Kubernetes Concepts for SRE

**Pod Phases:**
- `Pending`: Pod accepted but not yet running (scheduling, image pull)
- `Running`: Pod bound to node, at least one container running
- `Succeeded`: All containers terminated successfully
- `Failed`: All containers terminated, at least one failed
- `Unknown`: Pod state couldn't be determined

**Common Failure Patterns:**
- `CrashLoopBackOff`: Container crashing repeatedly
- `ImagePullBackOff`: Unable to pull container image
- `OOMKilled`: Container killed due to out-of-memory
- `Evicted`: Pod evicted due to resource pressure
- `Pending` (prolonged): Unable to schedule pod

**Pod Conditions:**
- `PodScheduled`: Pod has been scheduled to a node
- `ContainersReady`: All containers are ready
- `Initialized`: All init containers have completed
- `Ready`: Pod is ready to serve traffic

**Event Reasons to Watch For:**
- `FailedScheduling`: Pod can't be scheduled (resource constraints, node selector)
- `FailedMount`: Volume mount failures
- `BackOff`: Container failing to start
- `Unhealthy`: Liveness/readiness probe failures
- `Killing`: Pod being terminated
