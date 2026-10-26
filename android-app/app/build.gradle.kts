// Privi for Android: a Trusted Web Activity that opens the Privi website full screen in Chrome.
plugins {
    id("com.android.application")
}

val run = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toInt()

android {
    namespace = "us.priviflow.privi"
    compileSdk = 36

    defaultConfig {
        applicationId = "us.priviflow.privi"
        minSdk = 23
        targetSdk = 36
        versionCode = run
        versionName = "1.0.$run"
    }

    signingConfigs {
        create("upload") {
            // Optional local signing; CI builds unsigned and the bundle is signed with jarsigner afterwards.
            val ks = System.getenv("PRIVI_KEYSTORE_PATH")
            if (ks != null) {
                storeFile = file(ks)
                storePassword = System.getenv("PRIVI_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("PRIVI_KEY_ALIAS")
                keyPassword = System.getenv("PRIVI_KEYSTORE_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (System.getenv("PRIVI_KEYSTORE_PATH") != null) {
                signingConfig = signingConfigs.getByName("upload")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("com.google.androidbrowserhelper:androidbrowserhelper:2.5.0")
}
