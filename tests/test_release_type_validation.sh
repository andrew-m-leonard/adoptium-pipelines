#!/bin/bash
################################################################################
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
################################################################################
# Test script to demonstrate RELEASE_TYPE parameter validation

set +e  # Don't exit on error so we can see all test results

echo "=========================================="
echo "Testing RELEASE_TYPE Parameter Validation"
echo "=========================================="
echo ""

# Test 1: Valid value - NIGHTLY
echo "Test 1: Valid value - NIGHTLY"
python3 ../scripts/lib/load-json-config.py \
    --jdk-version jdk21u \
    --variant temurin \
    --target-os linux \
    --architecture x64 \
    --release-type NIGHTLY \
    --config-dir ../configurations \
    --output-dir /tmp/test-output 2>&1 | head -5
echo "Exit code: $?"
echo ""

# Test 2: Valid value - WEEKLY
echo "Test 2: Valid value - WEEKLY"
python3 ../scripts/lib/load-json-config.py \
    --jdk-version jdk21u \
    --variant temurin \
    --target-os linux \
    --architecture x64 \
    --release-type WEEKLY \
    --config-dir ../configurations \
    --output-dir /tmp/test-output 2>&1 | head -5
echo "Exit code: $?"
echo ""

# Test 3: Valid value - RELEASE
echo "Test 3: Valid value - RELEASE"
python3 ../scripts/lib/load-json-config.py \
    --jdk-version jdk21u \
    --variant temurin \
    --target-os linux \
    --architecture x64 \
    --release-type RELEASE \
    --config-dir ../configurations \
    --output-dir /tmp/test-output 2>&1 | head -5
echo "Exit code: $?"
echo ""

# Test 4: Invalid value - lowercase
echo "Test 4: Invalid value - 'nightly' (lowercase)"
python3 ../scripts/lib/load-json-config.py \
    --jdk-version jdk21u \
    --variant temurin \
    --target-os linux \
    --architecture x64 \
    --release-type nightly \
    --config-dir ../configurations \
    --output-dir /tmp/test-output 2>&1
echo "Exit code: $?"
echo ""

# Test 5: Invalid value - typo
echo "Test 5: Invalid value - 'RELASE' (typo)"
python3 ../scripts/lib/load-json-config.py \
    --jdk-version jdk21u \
    --variant temurin \
    --target-os linux \
    --architecture x64 \
    --release-type RELASE \
    --config-dir ../configurations \
    --output-dir /tmp/test-output 2>&1
echo "Exit code: $?"
echo ""

# Test 6: Invalid value - random string
echo "Test 6: Invalid value - 'FOOBAR'"
python3 ../scripts/lib/load-json-config.py \
    --jdk-version jdk21u \
    --variant temurin \
    --target-os linux \
    --architecture x64 \
    --release-type FOOBAR \
    --config-dir ../configurations \
    --output-dir /tmp/test-output 2>&1
echo "Exit code: $?"
echo ""

# Test 7: No value provided (should use default NIGHTLY)
echo "Test 7: No --release-type provided (should default to NIGHTLY)"
python3 ../scripts/lib/load-json-config.py \
    --jdk-version jdk21u \
    --variant temurin \
    --target-os linux \
    --architecture x64 \
    --config-dir ../configurations \
    --output-dir /tmp/test-output 2>&1 | head -5
echo "Exit code: $?"
echo ""

echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo "Tests 1-3: Should succeed (exit code 0)"
echo "Tests 4-6: Should fail with validation error (exit code 2)"
echo "Test 7: Should succeed with default NIGHTLY (exit code 0)"

# Made with Bob
