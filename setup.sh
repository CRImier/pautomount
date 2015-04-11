cp pautomount.py /usr/bin/pautomount
cp pautomount.service /etc/systemd/system/
chmod +x /usr/bin/pautomount
cp pautomount.init /etc/init.d/pautomount
chmod +x /etc/init.d/pautomount
cp pautomount.conf.example /etc/pautomount.conf
update-rc.d pautomount defaults
systemctl enable pautomount
systemctl start pautomount
echo "Now edit /etc/pautomount.conf so that all the partitions mounted by /etc/fstab are in the exception list."
echo "Then, set 'noexecute' in the 'globals' section to 'false' or remove this option"
