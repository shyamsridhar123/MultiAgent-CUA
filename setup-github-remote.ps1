# PowerShell script to set up Git repository and push to GitHub
# Usage: .\setup-github-remote.ps1

# Set the GitHub repository URL
$GITHUB_REPO_URL = "https://github.com/shyamsridhar123/MultiAgent-CUA.git"
$GITHUB_BRANCH = "main"

Write-Host "Setting up Git repository for MultiAgent-CUA..." -ForegroundColor Green

# Check if Git is installed
if (!(Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git is not installed. Please install Git and try again." -ForegroundColor Red
    exit 1
}

# Check if already a Git repository
if (!(Test-Path .\.git)) {
    Write-Host "Initializing Git repository..." -ForegroundColor Yellow
    git init
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to initialize Git repository." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "Git repository already initialized." -ForegroundColor Cyan
}

# Check if remote origin exists
$remoteExists = git remote | Select-String -Pattern "origin" -Quiet

if (!$remoteExists) {
    Write-Host "Adding remote origin: $GITHUB_REPO_URL" -ForegroundColor Yellow
    git remote add origin $GITHUB_REPO_URL
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to add remote origin." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "Updating remote origin URL: $GITHUB_REPO_URL" -ForegroundColor Yellow
    git remote set-url origin $GITHUB_REPO_URL
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to update remote origin." -ForegroundColor Red
        exit 1
    }
}

# Verify remote
Write-Host "Verifying remote..." -ForegroundColor Yellow
git remote -v

# Configure user information if not already set
$userNameSet = git config --get user.name
$userEmailSet = git config --get user.email

if (!$userNameSet -or !$userEmailSet) {
    Write-Host "Please configure your Git user information:" -ForegroundColor Yellow
    
    if (!$userNameSet) {
        $userName = Read-Host "Enter your name for Git commits"
        git config user.name "$userName"
    }
    
    if (!$userEmailSet) {
        $userEmail = Read-Host "Enter your email for Git commits"
        git config user.email "$userEmail"
    }
}

# Add all files
Write-Host "Adding files to Git..." -ForegroundColor Yellow
git add .

# Commit files
Write-Host "Committing files..." -ForegroundColor Yellow
$commitMessage = Read-Host "Enter a commit message [Initial commit of MultiAgent-CUA]"

if ([string]::IsNullOrEmpty($commitMessage)) {
    $commitMessage = "Initial commit of MultiAgent-CUA"
}

git commit -m "$commitMessage"

# Push to GitHub
Write-Host "Ready to push to GitHub repository: $GITHUB_REPO_URL" -ForegroundColor Green
Write-Host "Choose an option:" -ForegroundColor Yellow
Write-Host "1. Push to $GITHUB_BRANCH branch" -ForegroundColor Cyan
Write-Host "2. Force push to $GITHUB_BRANCH branch (WARNING: This will overwrite remote changes)" -ForegroundColor Red
Write-Host "3. Exit without pushing" -ForegroundColor Gray

$choice = Read-Host "Enter your choice (1-3)"

switch ($choice) {
    "1" {
        Write-Host "Pushing to $GITHUB_BRANCH branch..." -ForegroundColor Yellow
        git push -u origin $GITHUB_BRANCH
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Failed to push to GitHub. The repository may not exist or you may not have permission." -ForegroundColor Red
            Write-Host "You can create the repository at: https://github.com/new" -ForegroundColor Yellow
        } else {
            Write-Host "Successfully pushed to GitHub!" -ForegroundColor Green
        }
    }
    "2" {
        Write-Host "Force pushing to $GITHUB_BRANCH branch..." -ForegroundColor Red
        git push -u origin $GITHUB_BRANCH --force
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Failed to push to GitHub. The repository may not exist or you may not have permission." -ForegroundColor Red
            Write-Host "You can create the repository at: https://github.com/new" -ForegroundColor Yellow
        } else {
            Write-Host "Successfully pushed to GitHub!" -ForegroundColor Green
        }
    }
    "3" {
        Write-Host "Exiting without pushing. You can push later using 'git push -u origin $GITHUB_BRANCH'" -ForegroundColor Yellow
    }
    default {
        Write-Host "Invalid choice. Exiting without pushing." -ForegroundColor Red
    }
}

Write-Host "Setup complete! Your local repository is now connected to GitHub." -ForegroundColor Green
Write-Host "Repository URL: $GITHUB_REPO_URL" -ForegroundColor Cyan
