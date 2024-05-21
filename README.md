# Proteomics and Phosphoproteomics Pipeline

## Environment setup
<details>
  <summary>Set up python2.7</summary>

To set up python2.7 on MacOs

* Follow https://stackoverflow.com/questions/67380286/anaconda-channel-for-installing-python-2-7  
  
* Install additional packages with [Env/py27.yml](https://github.com/zhenzuo2/Proteomics-and-Phosphoproteomics-Pipeline/blob/main/Env/py27.yml)  

Then run 

```
conda create -n py27 --f py27.yml
```

To active it  

```
source /opt/homebrew/Caskroom/mambaforge/base/etc/profile.d/conda.sh;  
conda activate py27;  
```

</details>

<details>
  <summary>Set up Viper</summary>
  
* Follow https://www.bioconductor.org/packages/release/bioc/html/viper.html

```
if (!require("BiocManager", quietly = TRUE))
    install.packages("BiocManager")

BiocManager::install("viper")
```
</details>

