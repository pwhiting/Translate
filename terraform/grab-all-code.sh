find . -type f \( -name "*.tf" -o -name "Dockerfile" -o -name "*.txt" -o -name "*.json" -o -name "*.py" -o -name "*.yaml" \) ! -name "terraform*"  -exec sh -c "echo \# File: {} && cat {}" \; | pbcopy
