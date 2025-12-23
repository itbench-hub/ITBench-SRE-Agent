"""Few-shot examples for reasoning evaluation."""

FULLY_CORRECT_REASONING_FEW_SHOT = """## Below are some examples where the "Root Cause Reasoning Accuracy" (Metric 2) should be awarded full credit (score = 100).
"""

PARTIALLY_CORRECT_REASONING_FEW_SHOT = """## Below are some examples where the "Root Cause Reasoning Accuracy" (Metric 2) should be awarded partial credit (score = 50).
"""

INCIDENT_SPECIFIC_FULLY_CORRECT_REASONING = {
    "11": [
        "ConfigMap 'flagd-config' was updated to toggle 'kafkaqueueproblems', triggering flagd's in-cluster watcher to reload feature-flag definitions",
        "Modification of 'flagd-config' activated the kafkaqueueproblems chaos injection path, flooding Kafka topics and saturating the network'"
    ],
    "17": [
        "Chaos-mesh Schedule 'otel-demo-product-catalog-network-delay' fired and spawned the NetworkChaos experiment",
    ],
    "19": ["Schedule advanced its status.time and spawned a NetworkChaos CR"],
    "21": ["Chaos Mesh StressChaos resource injects memory stress on valkey-cart pods"],
    "25": ["The `otel-demo-recommendation-cpu-stress` Schedule entity orchestrates CPU stress experiments on the `recommendation` service pods."],
    "29": ["JVMChaos experiment 'AllInjected' condition turned true on the pod"],
    "80": ["Schedule 'otel-demo-checkout-kafka-network-partition' spawned the NetworkChaos experiment"],
    "81": ["Schedule 'otel-demo-shipping-quote-network-partition' status.active set to true, triggering creation of NetworkChaos CR"],
    "83": ["Chaos schedule 'otel-demo-email-checkout-network-partition' became active and created a NetworkChaos CR", "Chaos-Mesh schedule activated a network partition experiment","Chaos-mesh Schedule triggered a recurring NetworkChaos experiment on the checkout pod"],
    "91": ["Chaos-Mesh injected a network partition on kafka-79d9859bc6-kf97j, dropping all packets","Chaos Schedule controller spawned a NetworkChaos CR"]
}

INCIDENT_SPECIFIC_PARTIALLY_CORRECT_REASONING = {
    "14": ["ConfigMap flagd-config changed to enable adfailure flag"],
    "15": ["ConfigMap flagd-config modified to set adfailure defaultVariant to on"],
    "18": ["PodChaos injected artificial network latency into product-catalog pods"]
}


