package com.example.alphamaxxin

import android.annotation.SuppressLint
import android.os.Bundle
import android.webkit.WebView
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.launch
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }

        enableEdgeToEdge()
        setContent {
            MaterialTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
                    MainScreen(modifier = Modifier.padding(innerPadding))
                }
            }
        }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun MainScreen(modifier: Modifier = Modifier) {
    var targetInput by remember { mutableStateOf("Portfolio.md") }
    var agentInput by remember { mutableStateOf("Master Orchestrator") }
    var htmlContent by remember { mutableStateOf("") }
    var isLoading by remember { mutableStateOf(false) }
    val coroutineScope = rememberCoroutineScope()

    Column(modifier = modifier.fillMaxSize().padding(16.dp)) {
        Text(text = "AlphaMaxxin Mobile", style = MaterialTheme.typography.headlineMedium, color = MaterialTheme.colorScheme.primary)
        Spacer(modifier = Modifier.height(16.dp))
        
        OutlinedTextField(
            value = targetInput,
            onValueChange = { targetInput = it },
            label = { Text("Analysis Target (Ticker or Portfolio.md)") },
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(modifier = Modifier.height(8.dp))
        
        OutlinedTextField(
            value = agentInput,
            onValueChange = { agentInput = it },
            label = { Text("Agent (e.g. Master Orchestrator, US Macro Analyst)") },
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(modifier = Modifier.height(16.dp))

        Button(
            onClick = {
                if (targetInput.isBlank() || agentInput.isBlank()) return@Button
                isLoading = true
                htmlContent = ""
                
                coroutineScope.launch {
                    try {
                        val resultHtml = withContext(Dispatchers.IO) {
                            val py = Python.getInstance()
                            val runnerModule = py.getModule("runner")
                            val guiModule = py.getModule("gui")
                            
                            // Call run_agent_sync from Python
                            val markdownResult = runnerModule.callAttr("run_agent_sync", agentInput, targetInput).toString()
                            
                            // Render to HTML using gui module
                            val title = "$agentInput — ${targetInput.uppercase().replace(".MD", "")}"
                            guiModule.callAttr("render_report_html", title, markdownResult).toString()
                        }
                        htmlContent = resultHtml
                    } catch (e: Exception) {
                        htmlContent = "<html><body><h3>Error occurred:</h3><pre>${e.message}</pre></body></html>"
                        e.printStackTrace()
                    } finally {
                        isLoading = false
                    }
                }
            },
            modifier = Modifier.fillMaxWidth(),
            enabled = !isLoading
        ) {
            Text(if (isLoading) "Generating Report..." else "Generate Report")
        }

        Spacer(modifier = Modifier.height(16.dp))

        if (isLoading) {
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }

        if (htmlContent.isNotEmpty()) {
            AndroidView(
                modifier = Modifier.fillMaxSize(),
                factory = { context ->
                    WebView(context).apply {
                        settings.javaScriptEnabled = true
                        loadDataWithBaseURL(null, htmlContent, "text/html", "UTF-8", null)
                    }
                },
                update = { webView ->
                    webView.loadDataWithBaseURL(null, htmlContent, "text/html", "UTF-8", null)
                }
            )
        }
    }
}
