mv pautomount.py /usr/bin/pautomount
chmod +x /usr/bin/pautomount
mv pautomount.init /etc/init.d/pautomount
chmod +x /etc/init.d/pautomount
mv pautomount.conf.example /etc/pautomount.conf
update-rc.d pautomount defaults
echo "Now edit /etc/pautomount.conf so that all the partitions mounted by /etc/fstab are in the exception list."
echo "Then, set 'noexecute' in the 'globals' section to 'false' or remove this option"
