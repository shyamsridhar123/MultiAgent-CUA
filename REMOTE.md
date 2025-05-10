# Setting Up GitHub Remote Repository

This document provides instructions for setting up and connecting this codebase to the GitHub repository at `https://github.com/shyamsridhar123/MultiAgent-CUA`.

## Initial Setup

If you haven't yet connected this local repository to GitHub, follow these steps:

1. Ensure Git is installed on your machine
2. Initialize a local Git repository (if not already done):

```powershell
git init
```

3. Add the GitHub repository as the remote origin:

```powershell
git remote add origin https://github.com/shyamsridhar123/MultiAgent-CUA.git
```

4. Verify the remote is properly configured:

```powershell
git remote -v
```

## Pushing Code to GitHub

To push your code to the GitHub repository:

```powershell
# Add all files to the commit
git add .

# Create a commit with a message
git commit -m "Initial commit of MultiAgent-CUA"

# Push to the main branch
git push -u origin main
```

If the repository already has content and you want to force push:

```powershell
git push -u origin main --force
```

Note: Force pushing should be used with caution as it can overwrite remote changes.

## Branch Management

To create and work on a new feature branch:

```powershell
# Create and checkout a new branch
git checkout -b feature/new-feature

# Make your changes and commit them
git add .
git commit -m "Add new feature"

# Push the branch to GitHub
git push -u origin feature/new-feature
```

## Updating from Remote

To update your local repository with changes from GitHub:

```powershell
git pull origin main
```

## Creating a Pull Request

After pushing your branch to GitHub, you can create a pull request:

1. Go to `https://github.com/shyamsridhar123/MultiAgent-CUA`
2. Click on "Pull requests"
3. Click the "New pull request" button
4. Select your branch and provide a description of your changes
5. Click "Create pull request"

## Troubleshooting

If you encounter issues with authentication, consider using:

```powershell
# For HTTPS authentication
git remote set-url origin https://github.com/shyamsridhar123/MultiAgent-CUA.git

# Or for SSH authentication (if you have SSH keys set up)
git remote set-url origin git@github.com:shyamsridhar123/MultiAgent-CUA.git
```
