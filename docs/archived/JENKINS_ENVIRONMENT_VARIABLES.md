# Jenkins Environment Variables: environment{} vs env.VAR

## Your Discovery

✅ **`env.BUILD_UID` works** - Can be set dynamically and persists across stages and restarts
❌ **`environment { BUILD_UID = '' }` doesn't work** - Acts as read-only, cannot be modified in stages

## The Key Difference

### 1. `environment {}` Block (Declarative)

```groovy
pipeline {
    environment {
        BUILD_UID = ''  // ❌ Read-only after initialization
    }

    stages {
        stage('Test') {
            steps {
                script {
                    env.BUILD_UID = "new-value"  // ❌ DOESN'T WORK!
                    println env.BUILD_UID        // Still shows ''
                }
            }
        }
    }
}
```

**Characteristics:**
- ❌ **Immutable** - Cannot be changed after initialization
- ✅ **Declarative** - Defined at pipeline level
- ✅ **Visible in UI** - Shows in environment variables list
- ❌ **Cannot be set dynamically** - Value must be known at parse time
- ✅ **Can use expressions** - But only evaluated once at start

**Use Case:** Static configuration values that never change
```groovy
environment {
    APP_NAME = 'my-app'
    DEPLOY_ENV = 'production'
    JAVA_HOME = '/usr/lib/jvm/java-11'
}
```

### 2. `env.VAR` (Scripted/Dynamic)

```groovy
pipeline {
    // No environment block

    stages {
        stage('Test') {
            steps {
                script {
                    env.BUILD_UID = "new-value"  // ✅ WORKS!
                    println env.BUILD_UID        // Shows 'new-value'
                }
            }
        }
    }
}
```

**Characteristics:**
- ✅ **Mutable** - Can be changed anytime
- ✅ **Dynamic** - Can be set based on runtime conditions
- ✅ **Persists** - Available in all subsequent stages
- ✅ **Survives restarts** - Value persists when restarting from stage
- ⚠️ **Not in UI** - Doesn't show in environment variables list (unless set)

**Use Case:** Dynamic values that need to be computed or changed
```groovy
script {
    env.BUILD_UID = "${currentBuild.startTimeInMillis}-${UUID.randomUUID()}"
    env.COMPUTED_VALUE = someFunction()
}
```

## Why `environment {}` Variables Are Read-Only

### Jenkins Pipeline Execution Model

1. **Parse Phase** - Jenkins parses the entire Jenkinsfile
   - `environment {}` block is evaluated
   - Values are set and locked

2. **Execution Phase** - Stages run
   - `environment {}` variables are read-only
   - `env.VAR` assignments work

### Example of the Problem

```groovy
pipeline {
    environment {
        // This is evaluated ONCE at parse time
        BUILD_UID = ''
    }

    stages {
        stage('Init') {
            steps {
                script {
                    // This tries to modify a read-only variable
                    env.BUILD_UID = "abc123"  // ❌ Silently fails or ignored

                    println "BUILD_UID: ${env.BUILD_UID}"  // Still shows ''
                }
            }
        }
    }
}
```

**Why it fails:**
- `environment { BUILD_UID = '' }` creates a read-only binding
- `env.BUILD_UID = "abc123"` tries to modify it
- Jenkins ignores the modification (or it has no effect)

## The Correct Pattern for BUILD_UID

### ✅ Option 1: Use `env.VAR` Only (Recommended)

```groovy
pipeline {
    agent any

    parameters {
        string(name: 'BUILD_UID', defaultValue: '')
    }

    // NO environment block for BUILD_UID

    stages {
        stage('Initialize') {
            steps {
                script {
                    // Set env.BUILD_UID dynamically
                    if (!params.BUILD_UID) {
                        env.BUILD_UID = "${currentBuild.startTimeInMillis}-${UUID.randomUUID()}"
                    } else {
                        env.BUILD_UID = params.BUILD_UID
                    }

                    println "BUILD_UID: ${env.BUILD_UID}"
                }
            }
        }

        stage('Use It') {
            steps {
                script {
                    println "BUILD_UID: ${env.BUILD_UID}"  // ✅ Works!
                }
            }
        }
    }
}
```

### ❌ Option 2: Use `environment {}` with Expression (Doesn't Work for Dynamic Values)

```groovy
pipeline {
    environment {
        // ❌ This doesn't work - UUID is evaluated once at parse time
        BUILD_UID = "${UUID.randomUUID()}"
    }

    stages {
        stage('Test') {
            steps {
                script {
                    // All builds get the SAME UUID!
                    println env.BUILD_UID
                }
            }
        }
    }
}
```

**Problem:** Expression is evaluated once when Jenkinsfile is parsed, not per build.

### ✅ Option 3: Hybrid Approach (For Static + Dynamic)

```groovy
pipeline {
    environment {
        // Static values in environment block
        APP_NAME = 'my-app'
        DEPLOY_ENV = 'production'
    }

    // Dynamic values set in stages
    stages {
        stage('Initialize') {
            steps {
                script {
                    // Dynamic values via env.VAR
                    env.BUILD_UID = "${currentBuild.startTimeInMillis}-${UUID.randomUUID()}"
                    env.GIT_COMMIT_SHORT = env.GIT_COMMIT.take(8)
                }
            }
        }
    }
}
```

## Comparison Table

| Feature | `environment {}` | `env.VAR` |
|---------|------------------|-----------|
| **Mutability** | ❌ Read-only | ✅ Mutable |
| **When Evaluated** | Parse time (once) | Runtime (per build) |
| **Dynamic Values** | ❌ No | ✅ Yes |
| **Persists Across Stages** | ✅ Yes | ✅ Yes |
| **Survives Restart** | ✅ Yes | ✅ Yes |
| **Visible in UI** | ✅ Yes | ⚠️ Sometimes |
| **Can Use Functions** | ⚠️ Limited | ✅ Yes |
| **Best For** | Static config | Dynamic values |

## Real-World Examples

### Static Configuration (Use `environment {}`)

```groovy
pipeline {
    environment {
        DOCKER_REGISTRY = 'docker.io'
        APP_NAME = 'my-application'
        JAVA_VERSION = '11'
        MAVEN_OPTS = '-Xmx1024m'
    }
}
```

### Dynamic Values (Use `env.VAR`)

```groovy
pipeline {
    stages {
        stage('Initialize') {
            steps {
                script {
                    // Generate unique ID
                    env.BUILD_UID = "${currentBuild.startTimeInMillis}-${UUID.randomUUID()}"

                    // Compute based on conditions
                    env.DEPLOY_TARGET = (env.BRANCH_NAME == 'main') ? 'production' : 'staging'

                    // Extract from other variables
                    env.GIT_COMMIT_SHORT = env.GIT_COMMIT.take(8)

                    // Read from file
                    env.VERSION = readFile('VERSION').trim()
                }
            }
        }
    }
}
```

## Why Your Test Worked

Your test worked because you **didn't use `environment {}`** block:

```groovy
pipeline {
    // ✅ No environment block

    parameters {
        string(name: 'BUILD_UID', defaultValue: '')
    }

    stages {
        stage('Initialize') {
            steps {
                script {
                    // ✅ Direct assignment to env.BUILD_UID
                    env.BUILD_UID = "${timestamp}-${random}"
                }
            }
        }
    }
}
```

This allowed `env.BUILD_UID` to be:
- ✅ Set dynamically in Stage 1
- ✅ Read in Stage 2 and 3
- ✅ Preserved across restarts (via parameter)

## Best Practice for BUILD_UID

```groovy
pipeline {
    agent any

    parameters {
        string(
            name: 'BUILD_UID',
            defaultValue: '',
            description: 'Unique ID for this pipeline run (auto-generated if empty)'
        )
    }

    // ✅ NO environment block for BUILD_UID

    stages {
        stage('Initialize') {
            steps {
                script {
                    // ✅ Set env.BUILD_UID dynamically
                    if (!params.BUILD_UID || params.BUILD_UID == '') {
                        def timestamp = currentBuild.startTimeInMillis
                        def random = UUID.randomUUID().toString().take(8)
                        env.BUILD_UID = "${timestamp}-${random}"
                        println "🆕 Generated BUILD_UID: ${env.BUILD_UID}"
                    } else {
                        env.BUILD_UID = params.BUILD_UID
                        println "♻️ Reusing BUILD_UID: ${env.BUILD_UID}"
                    }

                    currentBuild.description = "BUILD_UID: ${env.BUILD_UID}"
                }
            }
        }

        stage('Build') {
            steps {
                script {
                    println "BUILD_UID: ${env.BUILD_UID}"  // ✅ Available

                    // Store in metadata
                    def metadata = [BUILD_UID: env.BUILD_UID]
                    writeJSON file: 'workspace/metadata.json', json: metadata
                    archiveArtifacts 'workspace/**/*'
                }
            }
        }

        stage('Sign') {
            steps {
                script {
                    println "BUILD_UID: ${env.BUILD_UID}"  // ✅ Still available

                    // Validate against metadata
                    copyArtifacts(...)
                    def metadata = readJSON file: 'workspace/metadata.json'

                    if (metadata.BUILD_UID != env.BUILD_UID) {
                        error("BUILD_UID mismatch!")
                    }
                }
            }
        }
    }
}
```

## Summary

### The Rule

- **Static values** → Use `environment {}` block
- **Dynamic values** → Use `env.VAR` assignment
- **BUILD_UID** → Use `env.BUILD_UID` (dynamic, must be mutable)

### Why It Matters

Your discovery is critical because:
1. ✅ `env.BUILD_UID` works across stages and restarts
2. ❌ `environment { BUILD_UID }` would have broken everything
3. ✅ Now we know the correct pattern for workspace validation

### The Correct Pattern

```groovy
// ✅ DO THIS
env.BUILD_UID = generateUID()

// ❌ DON'T DO THIS
environment {
    BUILD_UID = generateUID()  // Won't work as expected
}
```

**Your test validated the approach - `env.BUILD_UID` is the way to go!**