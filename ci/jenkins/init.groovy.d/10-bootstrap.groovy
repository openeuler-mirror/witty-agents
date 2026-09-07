import hudson.plugins.git.BranchSpec
import hudson.plugins.git.GitSCM
import hudson.plugins.git.UserRemoteConfig
import hudson.model.User
import hudson.security.FullControlOnceLoggedInAuthorizationStrategy
import hudson.security.HudsonPrivateSecurityRealm
import hudson.triggers.SCMTrigger
import jenkins.model.Jenkins
import org.jenkinsci.plugins.workflow.cps.CpsScmFlowDefinition
import org.jenkinsci.plugins.workflow.job.WorkflowJob

def requiredEnv = { String name ->
    def value = System.getenv(name)?.trim()
    if (!value) {
        throw new IllegalStateException("Required environment variable is missing: ${name}")
    }
    value
}

def jenkins = Jenkins.get()
def adminUser = System.getenv('JENKINS_ADMIN_USER')?.trim() ?: 'admin'
def passwordFile = requiredEnv('JENKINS_ADMIN_PASSWORD_FILE')
def password = new File(passwordFile).text.trim()
if (!password) {
    throw new IllegalStateException("Jenkins admin password file is empty: ${passwordFile}")
}

def realm
if (jenkins.securityRealm instanceof HudsonPrivateSecurityRealm) {
    realm = jenkins.securityRealm
} else {
    realm = new HudsonPrivateSecurityRealm(false)
    jenkins.setSecurityRealm(realm)
}
if (User.getById(adminUser, false) == null) {
    realm.createAccount(adminUser, password)
}
jenkins.setAuthorizationStrategy(new FullControlOnceLoggedInAuthorizationStrategy(false))

def jobName = System.getenv('WITTY_AGENTS_JOB_NAME')?.trim() ?: 'witty-agent-package-ci'
def repoUrl = requiredEnv('WITTY_AGENTS_REPO_URL')
def branch = System.getenv('WITTY_AGENTS_BRANCH')?.trim() ?: '*/master'
def scriptPath = System.getenv('WITTY_AGENTS_SCRIPT_PATH')?.trim() ?: 'Jenkinsfile'
def credentialsId = System.getenv('WITTY_AGENTS_GIT_CREDENTIAL_ID')?.trim()

def remote = new UserRemoteConfig(repoUrl, null, null, credentialsId ?: null)
def scm
try {
    scm = new GitSCM([remote], [new BranchSpec(branch)], null, null, [])
} catch (MissingMethodException ignored) {
    scm = new GitSCM([remote], [new BranchSpec(branch)], false, [], null, null, [])
}

def job = jenkins.getItem(jobName)
if (job != null && !(job instanceof WorkflowJob)) {
    throw new IllegalStateException("Jenkins item already exists and is not a Pipeline Job: ${jobName}")
}
if (job == null) {
    job = jenkins.createProject(WorkflowJob, jobName)
}

job.setDescription('Witty Agents repository-level npm build, validation and publishing pipeline.')
job.setDefinition(new CpsScmFlowDefinition(scm, scriptPath, true))
if (job.getTrigger(SCMTrigger.class) == null) {
    job.addTrigger(new SCMTrigger('H/5 * * * *'))
}
job.save()
jenkins.save()

println("[witty-agents-bootstrap] Pipeline Job ready: ${jobName}")
println("[witty-agents-bootstrap] SCM: ${repoUrl} ${branch} -> ${scriptPath}")
